"""Email-code verification: prove control of <login>@stuba.sk with a one-time code, optionally enriched by LDAP.

The password is never involved. A code is sent to the school mailbox; entering it proves the person owns a real
STU account. LDAP enrichment (optional, needs the STU VPN) adds faculty + student/staff type and the AIS ID so
the identity fingerprint matches the Microsoft/SAML one; without it, a verified mailbox defaults to Študent.
Vyučujúci is never granted automatically — it always opens a moderator review.
"""

from __future__ import annotations

import logging
import re
import secrets
from asyncio import to_thread
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord

from stuard import texts as T
from stuard.domain.ldap_map import map_ldap_person, parse_person
from stuard.security.tokens import hash_token, subject_hmac
from stuard.services.mailer import Mailer
from stuard.timeutil import now_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

log = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I/L
CODE_LENGTH = 6
_LOGIN = re.compile(r"^[a-z][a-z0-9]{2,20}$")
_AIS = re.compile(r"^\d{4,12}$")

SendFn = Callable[[str, str, str], bool]
LookupFn = Callable[[str], "dict[str, object] | None"]


def _gen_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _normalize_login(raw: str) -> str | None:
    value = raw.strip().lower().split("@", 1)[0]
    return value if (_LOGIN.match(value) or _AIS.match(value)) else None


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    shown = local[:2] if len(local) > 2 else local[:1]
    return f"{shown}***@{domain}" if domain else "***"


class EmailVerifyService:
    def __init__(self, bot: StuardBot, send: SendFn | None = None, lookup: LookupFn | None = None) -> None:
        self.bot = bot
        self._mailer = Mailer(bot.settings)
        self._send: SendFn = send or self._mailer.send
        self._injected_send = send is not None
        self._lookup = lookup  # None → build an LdapDirectory from config per call

    def enabled(self) -> bool:
        override = self.bot.email_override
        return self.bot.cfg.email.enabled if override is None else override

    def _configured(self) -> bool:
        return self._injected_send or self._mailer.configured()

    def _do_lookup(self, login: str) -> dict[str, object] | None:
        if self._lookup is not None:
            return self._lookup(login)
        from stuard.services.ldapdir import LdapDirectory  # noqa: PLC0415 - lazy: avoids importing ldap3 unless used

        return LdapDirectory(self.bot.cfg.email.ldap).lookup(login)

    async def request_code(self, member: discord.Member, raw_login: str) -> str:
        bot = self.bot
        cfg = bot.cfg.email
        if not self.enabled():
            return T.EMAIL_DISABLED
        if not self._configured():
            return T.EMAIL_NOT_CONFIGURED
        login = _normalize_login(raw_login)
        if login is None:
            return T.EMAIL_BAD_LOGIN
        key = f"email:{member.id}"
        if not bot.verify_limiter.hit(key):
            minutes = max(1, round(bot.verify_limiter.retry_after(key) / 60))
            return T.VERIFY_RATE_LIMITED.format(minutes=minutes)

        domain = cfg.allowed_domains[0]
        person = None
        if cfg.ldap.enabled:
            attrs = await to_thread(self._do_lookup, login)
            if attrs is None:
                return T.EMAIL_NOT_FOUND
            person = parse_person(attrs)

        if person is not None:
            result = map_ldap_person(person, cfg)
            if result.rejected:
                return T.EMAIL_REJECTED
            outcome = "student" if result.status == "student" else ("teacher" if result.teacher_candidate else "review")
            to = person.email or f"{login}@{domain}"
            subject_id = person.ais_id or login
        else:
            outcome = "student" if cfg.without_ldap == "student" else "review"
            to = f"{login}@{domain}"
            subject_id = login

        code = _gen_code()
        subject = subject_hmac(bot.settings.hmac_key, f"{subject_id}@{domain}")
        await bot.repo.upsert_email_code(
            member.id,
            login=login,
            email=to,
            subject_hmac=subject,
            code_hash=hash_token(code),
            outcome=outcome,
            now=now_ts(),
            ttl=cfg.code_ttl_minutes * 60,
        )
        body = T.EMAIL_BODY.format(code=code, minutes=cfg.code_ttl_minutes)
        sent = await to_thread(self._send, to, T.EMAIL_SUBJECT, body)
        if not sent:
            await bot.repo.delete_email_code(member.id)
            return T.EMAIL_SEND_FAILED
        await bot.audit.log(
            "email_code_sent",
            target_id=member.id,
            detail={"domain": domain, "outcome": outcome, "ldap": cfg.ldap.enabled},
            notify=False,
        )
        return T.EMAIL_SENT.format(email=_mask(to), minutes=cfg.code_ttl_minutes)

    async def submit_code(self, member: discord.Member, raw_code: str) -> str:
        bot = self.bot
        cfg = bot.cfg.email
        if not self.enabled():
            return T.EMAIL_DISABLED
        row = await bot.repo.get_email_code(member.id)
        now = now_ts()
        if row is None:
            return T.EMAIL_NO_PENDING
        if row.expires_at <= now:
            await bot.repo.delete_email_code(member.id)
            return T.EMAIL_EXPIRED
        attempts = await bot.repo.bump_email_attempts(member.id)
        if attempts > cfg.max_attempts:
            await bot.repo.delete_email_code(member.id)
            return T.EMAIL_TOO_MANY
        if hash_token(raw_code.strip().upper()) != row.code_hash:
            return T.EMAIL_WRONG_CODE.format(left=max(0, cfg.max_attempts - attempts))

        await bot.repo.delete_email_code(member.id)
        bound = await bot.repo.bind_identity(row.subject_hmac, member.id, (), now)
        if bound == "conflict":
            await bot.audit.log("email_duplicate_account", target_id=member.id)
            return T.EMAIL_CONFLICT
        if bound == "tombstoned":
            return T.EMAIL_TOMBSTONED.format(duration=T.days_sk(bot.cfg.retention.tombstone_days))

        if row.outcome == "student":
            await bot.repo.set_member_status(
                member.id,
                status="student",
                method=None,  # 'email' is not in the members.method CHECK; the audit log records the method
                now=now,
                valid_until=bot.members.valid_until_for("student", now),
                mark_verified=True,
            )
            await bot.roles.sync_user(member.id, reason="STUard: overenie e-mailovým kódom")
            await bot.audit.log("verified_email", target_id=member.id, detail={"to": "student"})
            return T.EMAIL_VERIFIED
        if row.outcome == "teacher":
            await bot.reviews.open_sso_review(member.id, "sso_teacher", (), suggest="teacher", via="email")
            await bot.audit.log("verified_email", target_id=member.id, detail={"to": "teacher_review"})
            return T.EMAIL_TEACHER_PENDING
        await bot.reviews.open_sso_review(member.id, "sso_status", (), suggest=None, via="email")
        await bot.audit.log("verified_email", target_id=member.id, detail={"to": "review"})
        return T.EMAIL_REVIEW_PENDING
