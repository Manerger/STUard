"""Verification: issue personal links and apply the result of a validated Microsoft 365 or STU login."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from stuard.domain.lifecycle import status_after_sso
from stuard.domain.mapping import map_affiliations, map_employee_type
from stuard.security.tokens import hash_token, new_token
from stuard.timeutil import now_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

LINK_TTL_SECONDS = 600
FLOW_TTL_SECONDS = 900
VERIFIED_STATUSES = ("student", "applicant", "alumni")

OutcomeCode = Literal["verified", "former", "pending", "conflict", "tombstoned", "rejected"]


@dataclass(frozen=True, slots=True)
class Outcome:
    code: OutcomeCode
    status: str | None = None
    teacher_review: bool = False


class VerificationService:
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    def sso_enabled(self) -> bool:
        override = self.bot.sso_override
        enabled = self.bot.cfg.sso.enabled if override is None else override
        return bool(enabled and self.bot.saml is not None)

    def microsoft_enabled(self) -> bool:
        override = self.bot.microsoft_override
        enabled = self.bot.cfg.microsoft.enabled if override is None else override
        return bool(enabled and self.bot.microsoft is not None)

    def manual_available(self) -> bool:
        override = self.bot.manual_override
        if override is not None:
            return override
        mode = self.bot.cfg.manual.mode
        automatic = self.sso_enabled() or self.microsoft_enabled()
        return mode == "always" or (mode == "when_sso_disabled" and not automatic)

    async def create_link(self, user_id: int) -> str:
        token = new_token()
        await self.bot.repo.create_flow(user_id, hash_token(token), now_ts(), LINK_TTL_SECONDS)
        return f"{self.bot.settings.public_base_url}/v?t={token}"

    async def _bind(self, user_id: int, subject_hmac: bytes, affiliations: Iterable[str], now: int) -> Outcome | None:
        """Bind the account to the Discord user; returns an Outcome only when that is refused."""
        bot = self.bot
        bound = await bot.repo.bind_identity(subject_hmac, user_id, affiliations, now)
        if bound == "conflict":
            other = await bot.repo.get_identity_by_subject(subject_hmac)
            await bot.audit.log(
                "sso_duplicate_account",
                target_id=user_id,
                detail={"already_linked_to": f"<@{other.user_id}>" if other else None},
            )
            return Outcome("conflict")
        if bound == "tombstoned":
            await bot.audit.log("sso_tombstoned_account", target_id=user_id)
            return Outcome("tombstoned")
        return None

    async def complete_sso(self, user_id: int, subject_hmac: bytes, affiliations: frozenset[str]) -> Outcome:
        bot = self.bot
        now = now_ts()
        affs = sorted(affiliations)
        result = map_affiliations(affiliations, bot.cfg.sso)
        if result.rejected:
            await bot.audit.log("sso_rejected", target_id=user_id, detail={"affiliations": affs})
            return Outcome("rejected")
        refused = await self._bind(user_id, subject_hmac, affiliations, now)
        if refused is not None:
            return refused

        member = await bot.repo.get_member(user_id)
        old_status = member.status if member else "unverified"
        is_teacher = bool(member and member.is_teacher)
        final_status = status_after_sso(old_status, result.status) or old_status
        await bot.repo.set_member_status(
            user_id,
            status=final_status,
            method="sso",
            now=now,
            valid_until=bot.members.valid_until_for(final_status, now),
            mark_verified=True,
        )

        teacher_review = False
        if result.teacher_candidate and not is_teacher:
            teacher_review = await bot.reviews.open_sso_review(user_id, "sso_teacher", affiliations, suggest="teacher")
        status_review = False
        if result.review and not (result.suggest is not None and final_status == result.suggest):
            status_review = await bot.reviews.open_sso_review(
                user_id, "sso_status", affiliations, suggest=result.suggest
            )

        await bot.audit.log(
            "verified_sso",
            target_id=user_id,
            detail={
                "from": old_status,
                "to": final_status,
                "affiliations": affs,
                "teacher_review": teacher_review or None,
                "status_review": status_review or None,
            },
        )
        await bot.roles.sync_user(user_id, reason="STUard: overenie cez STU")

        if final_status == "former_student":
            return Outcome("former", final_status, teacher_review)
        if final_status in VERIFIED_STATUSES:
            return Outcome("verified", final_status, teacher_review)
        if is_teacher and not status_review:
            return Outcome("verified", "teacher", teacher_review)
        return Outcome("pending", None, teacher_review)

    async def complete_microsoft(
        self, user_id: int, subject_hmac: bytes, login: str, employee_type: str | None
    ) -> Outcome:
        """Microsoft 365 login: `employeeType` decides Študent; Vyučujúci always goes to a moderator.

        A Microsoft login never removes a status — dropouts are handled by the yearly deadline or moderators.
        """
        bot = self.bot
        cfg = bot.cfg.microsoft
        now = now_ts()
        result = map_employee_type(employee_type, cfg)
        refused = await self._bind(user_id, subject_hmac, (), now)
        if refused is not None:
            return refused

        member = await bot.repo.get_member(user_id)
        old_status = member.status if member else "unverified"
        is_teacher = bool(member and member.is_teacher)
        final_status = result.status or old_status
        await bot.repo.set_member_status(
            user_id,
            status=final_status,
            method="microsoft",
            now=now,
            valid_until=bot.members.valid_until_for(final_status, now),
            mark_verified=True,
        )

        details = [employee_type] if employee_type else []
        shown_login = login if cfg.show_login_to_moderators else None
        teacher_review = False
        if result.teacher_candidate and not is_teacher:
            teacher_review = await bot.reviews.open_sso_review(
                user_id, "sso_teacher", details, suggest="teacher", login=shown_login, via="microsoft"
            )
        status_review = False
        if result.review and final_status not in VERIFIED_STATUSES:
            status_review = await bot.reviews.open_sso_review(
                user_id, "sso_status", details, suggest=result.suggest, login=shown_login, via="microsoft"
            )

        await bot.audit.log(
            "verified_microsoft",
            target_id=user_id,
            detail={
                "from": old_status,
                "to": final_status,
                "employee_type": employee_type or "—",
                "teacher_review": teacher_review or None,
                "status_review": status_review or None,
            },
        )
        await bot.roles.sync_user(user_id, reason="STUard: overenie cez Microsoft 365")

        if final_status in VERIFIED_STATUSES:
            return Outcome("verified", final_status, teacher_review)
        if is_teacher and not status_review:
            return Outcome("verified", "teacher", teacher_review)
        return Outcome("pending", None, teacher_review)
