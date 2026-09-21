from __future__ import annotations

from stuard.config import AppConfig, LdapCfg
from stuard.db.repos import Repo
from stuard.services.email_verify import EmailVerifyService
from tests.fakes import FakeBot, namespace

MTF_STUDENT = {
    "uid": ["xnovak"],
    "uisId": ["150309"],
    "employeeType": ["student"],
    "mail": ["xnovak@stuba.sk"],
    "host": ["mtf-stud"],
    "accountStatus": ["student:active", "mtf-stud:active"],
}


class Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, to: str, subject: str, body: str) -> bool:
        self.sent.append((to, subject, body))
        return True

    @property
    def last_code(self) -> str:
        # the code is the indented line in the body
        body = self.sent[-1][2]
        return next(line.strip() for line in body.splitlines() if line.strip() and line.startswith("    "))


def make_bot(repo: Repo, cfg: AppConfig, *, enabled: bool = True, ldap: bool = False, **email_over) -> FakeBot:
    email = cfg.email.model_copy(update={"enabled": enabled, "ldap": LdapCfg(enabled=ldap), **email_over})
    return FakeBot(repo, cfg.model_copy(update={"email": email}))


def service(bot: FakeBot, out: Outbox, lookup=None) -> EmailVerifyService:
    return EmailVerifyService(bot, send=out, lookup=lookup)  # type: ignore[arg-type]


async def request_and_code(svc: EmailVerifyService, out: Outbox, uid: int, login: str) -> str:
    await svc.request_code(namespace(id=uid), login)
    return out.last_code


# ---------------------------------------------------------------- no-LDAP path
async def test_email_only_verifies_a_student(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg)
    svc = service(bot, out)
    msg = await svc.request_code(namespace(id=1), "xnovak")
    assert "xn***@stuba.sk" in msg
    assert out.sent[0][0] == "xnovak@stuba.sk"
    result = await svc.submit_code(namespace(id=1), out.last_code)
    assert "Študent" in result
    member = await repo.get_member(1)
    assert member is not None and member.status == "student"
    assert await repo.get_identity_by_user(1) is not None  # bound for dup detection
    assert "verified_email" in bot.audit.actions


async def test_wrong_then_right_code(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg)
    svc = service(bot, out)
    code = await request_and_code(svc, out, 1, "xnovak")
    assert "Nesprávny kód" in await svc.submit_code(namespace(id=1), "WRONG1")
    assert "Študent" in await svc.submit_code(namespace(id=1), code)


async def test_too_many_attempts_invalidates_code(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg, max_attempts=2)
    svc = service(bot, out)
    code = await request_and_code(svc, out, 1, "xnovak")
    await svc.submit_code(namespace(id=1), "NOPE11")
    await svc.submit_code(namespace(id=1), "NOPE22")
    assert "Priveľa pokusov" in await svc.submit_code(namespace(id=1), code)  # even the correct code now fails
    assert await repo.get_member(1) is None


async def test_bad_login_rejected(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg)
    assert "školský login" in await service(bot, out).request_code(namespace(id=1), "a b c!")
    assert out.sent == []


async def test_numeric_ais_id_emails_the_alias(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg)
    await service(bot, out).request_code(namespace(id=1), "150309")
    assert out.sent[0][0] == "150309@stuba.sk"


async def test_disabled_service_refuses(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg, enabled=False)
    assert "nie je zapnuté" in await service(bot, out).request_code(namespace(id=1), "xnovak")


async def test_no_pending_code(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg)
    assert "Najprv si vyžiadaj" in await service(bot, out).submit_code(namespace(id=1), "ABC123")


async def test_one_account_cannot_verify_two_discords(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg)
    svc = service(bot, out)
    c1 = await request_and_code(svc, out, 1, "xnovak")
    await svc.submit_code(namespace(id=1), c1)
    c2 = await request_and_code(svc, out, 2, "xnovak")
    assert "iným Discord" in await svc.submit_code(namespace(id=2), c2)
    assert await repo.get_member(2) is None


# ---------------------------------------------------------------- LDAP-enriched path
async def test_ldap_student_verifies(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg, ldap=True)
    svc = service(bot, out, lookup=lambda _login: MTF_STUDENT)
    code = await request_and_code(svc, out, 1, "xnovak")
    assert "Študent" in await svc.submit_code(namespace(id=1), code)
    # LDAP gave the AIS ID → identity fingerprint matches what Microsoft/SAML would produce
    from stuard.security.tokens import subject_hmac
    expected = subject_hmac(bot.settings.hmac_key, "150309@stuba.sk")
    assert (await repo.get_identity_by_subject(expected)) is not None


async def test_ldap_other_faculty_student_becomes_outsider(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg, ldap=True)
    fei = {
        "uid": ["xfei"], "employeeType": ["student"], "host": ["fei-stud"],
        "accountStatus": ["fei-stud:active"], "mail": ["xfei@stuba.sk"],
    }
    svc = service(bot, out, lookup=lambda _login: fei)
    msg = await svc.request_code(namespace(id=1), "xfei")
    assert "xf***@stuba.sk" in msg and out.sent[0][0] == "xfei@stuba.sk"  # code sent to the STU mailbox
    result = await svc.submit_code(namespace(id=1), out.last_code)
    assert "Outsider" in result
    member = await repo.get_member(1)
    assert member is not None and member.status == "outsider"


async def test_ldap_other_faculty_non_student_rejected_before_sending(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg, ldap=True)
    staff = {"uid": ["xzamest"], "employeeType": ["employee"], "host": ["fei-zam"], "accountStatus": ["fei-zam:active"]}
    msg = await service(bot, out, lookup=lambda _login: staff).request_code(namespace(id=1), "xzamest")
    assert "nie si študentom MTF" in msg
    assert out.sent == []  # no code sent to a rejected account


async def test_ldap_login_not_found(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg, ldap=True)
    msg = await service(bot, out, lookup=lambda _login: None).request_code(namespace(id=1), "xghost")
    assert "nenašiel" in msg


async def test_ldap_staff_opens_teacher_review(repo: Repo, cfg: AppConfig) -> None:
    out = Outbox()
    bot = make_bot(repo, cfg, ldap=True)
    staff = {"uid": ["xteach"], "employeeType": ["employee"], "host": ["mtf-zam"], "mail": ["xteach@stuba.sk"]}
    svc = service(bot, out, lookup=lambda _login: staff)
    code = await request_and_code(svc, out, 1, "xteach")
    assert "Vyučujúci" in await svc.submit_code(namespace(id=1), code)
    assert bot.reviews.opened == [(1, "sso_teacher", "teacher")]
    member = await repo.get_member(1)
    assert member is None or member.status == "unverified"  # teacher never auto-granted
