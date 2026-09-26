from __future__ import annotations

import pytest

from stuard.config import AppConfig
from stuard.db.repos import Repo
from stuard.services.verification import Outcome, VerificationService
from stuard.timeutil import now_ts
from tests.fakes import FakeBot

S1, S2 = b"1" * 32, b"2" * 32


@pytest.fixture
def bot(repo: Repo, cfg: AppConfig) -> FakeBot:
    return FakeBot(repo, cfg)


def service(bot: FakeBot) -> VerificationService:
    return VerificationService(bot)  # type: ignore[arg-type]


async def complete(bot: FakeBot, user_id: int, subject: bytes, *affs: str) -> Outcome:
    return await service(bot).complete_sso(user_id, subject, frozenset(affs))


async def test_student_is_verified(bot: FakeBot, repo: Repo) -> None:
    assert await complete(bot, 1, S1, "student", "member") == Outcome("verified", "student", False)
    member = await repo.get_member(1)
    assert member is not None
    assert (member.status, member.method) == ("student", "sso")
    assert member.valid_until is not None and member.valid_until > now_ts()
    assert bot.roles.synced == [1]
    assert bot.reviews.opened == []
    assert "verified_sso" in bot.audit.actions


async def test_same_uis_account_cannot_verify_second_discord_account(bot: FakeBot, repo: Repo) -> None:
    await complete(bot, 1, S1, "student")
    assert (await complete(bot, 2, S1, "student")).code == "conflict"
    assert await repo.get_member(2) is None
    assert "sso_duplicate_account" in bot.audit.actions


async def test_staff_member_gets_teacher_review_only(bot: FakeBot, repo: Repo) -> None:
    assert await complete(bot, 1, S1, "staff", "member") == Outcome("pending", None, True)
    assert bot.reviews.opened == [(1, "sso_teacher", "teacher")]
    member = await repo.get_member(1)
    assert member is not None and member.status == "unverified" and not member.is_teacher


async def test_confirmed_teacher_logging_in_again(bot: FakeBot, repo: Repo) -> None:
    await repo.set_teacher(1, True)
    assert await complete(bot, 1, S1, "faculty") == Outcome("verified", "teacher", False)
    assert bot.reviews.opened == []


async def test_phd_student_who_is_employee(bot: FakeBot) -> None:
    assert await complete(bot, 1, S1, "student", "employee") == Outcome("verified", "student", True)
    assert bot.reviews.opened == [(1, "sso_teacher", "teacher")]


async def test_affiliate_needs_status_review(bot: FakeBot) -> None:
    assert (await complete(bot, 1, S1, "affiliate")).code == "pending"
    assert bot.reviews.opened == [(1, "sso_status", "applicant")]


async def test_confirmed_applicant_reverifying_needs_no_review(bot: FakeBot, repo: Repo) -> None:
    await repo.set_member_status(1, status="applicant", method="manual", now=100, valid_until=200)
    assert await complete(bot, 1, S1, "affiliate") == Outcome("verified", "applicant", False)
    assert bot.reviews.opened == []
    member = await repo.get_member(1)
    assert member is not None and member.valid_until is not None and member.valid_until > 200


async def test_student_without_student_affiliation_becomes_former(bot: FakeBot, repo: Repo) -> None:
    await complete(bot, 1, S1, "student")
    assert (await complete(bot, 1, S1, "member")).code == "former"
    member = await repo.get_member(1)
    assert member is not None and member.status == "former_student" and member.valid_until is None


async def test_graduate(bot: FakeBot) -> None:
    await complete(bot, 1, S1, "student")
    assert await complete(bot, 1, S1, "alum", "member") == Outcome("verified", "alumni", False)


async def test_rejected_when_unmatched_is_reject(repo: Repo, cfg: AppConfig) -> None:
    strict = cfg.model_copy(update={"sso": cfg.sso.model_copy(update={"unmatched": "reject"})})
    bot = FakeBot(repo, strict)
    assert (await complete(bot, 1, S1, "member")).code == "rejected"
    assert await repo.get_member(1) is None


async def test_recently_forgotten_account_is_blocked(bot: FakeBot, repo: Repo) -> None:
    await repo.add_tombstone(S2, now_ts() + 1000)
    assert (await complete(bot, 1, S2, "student")).code == "tombstoned"


def test_login_methods_and_manual_fallback(repo: Repo, cfg: AppConfig) -> None:
    fallback_only = cfg.model_copy(
        update={
            "manual": cfg.manual.model_copy(update={"mode": "when_sso_disabled"}),
            "microsoft": cfg.microsoft.model_copy(update={"enabled": False}),
        }
    )
    bot = FakeBot(repo, fallback_only)
    verification = service(bot)
    assert not verification.sso_enabled() and not verification.microsoft_enabled()
    assert verification.manual_available()
    bot.microsoft_override = True
    assert verification.microsoft_enabled() and not verification.manual_available()
    bot.microsoft = None  # no Microsoft app configured → cannot be on
    assert not verification.microsoft_enabled() and verification.manual_available()
    bot.sso_override = True
    assert verification.sso_enabled() and not verification.manual_available()
    bot.saml = None  # SAML files missing → SSO cannot be on
    assert not verification.sso_enabled()


def test_manual_review_stays_available_with_automatic_logins(bot: FakeBot) -> None:
    bot.sso_override = True
    bot.microsoft_override = True
    assert service(bot).manual_available()  # config.example.yaml: manual.mode = always


def test_manual_override_forces_state_regardless_of_mode(bot: FakeBot) -> None:
    verification = service(bot)
    assert verification.manual_available()  # config.example.yaml: manual.mode = always
    bot.manual_override = False  # admin: /admin manual off — everyone must log in
    assert not verification.manual_available()
    bot.manual_override = True  # admin: /admin manual on — e.g. to verify a teacher
    assert verification.manual_available()
    bot.manual_override = None  # back to the config mode
    assert verification.manual_available()


async def complete_ms(
    bot: FakeBot, user_id: int, subject: bytes, employee_type: str | None = "student", login: str = "xnovak@stuba.sk"
) -> Outcome:
    return await service(bot).complete_microsoft(user_id, subject, login, employee_type)


async def test_microsoft_student_account_gets_student(bot: FakeBot, repo: Repo) -> None:
    assert await complete_ms(bot, 1, S1) == Outcome("verified", "student", False)
    member = await repo.get_member(1)
    assert member is not None and (member.status, member.method) == ("student", "microsoft")
    assert member.valid_until is not None
    assert bot.roles.synced == [1]
    assert bot.reviews.opened == []
    assert "verified_microsoft" in bot.audit.actions


async def test_microsoft_employee_gets_a_teacher_review_only(bot: FakeBot, repo: Repo) -> None:
    assert await complete_ms(bot, 1, S1, "employee") == Outcome("pending", None, True)
    assert bot.reviews.opened == [(1, "sso_teacher", "teacher")]
    assert bot.reviews.logins == ["xnovak@stuba.sk"]
    member = await repo.get_member(1)
    assert member is not None and member.status == "unverified" and not member.is_teacher


async def test_microsoft_missing_account_type_needs_a_moderator(bot: FakeBot, repo: Repo) -> None:
    assert (await complete_ms(bot, 1, S1, None)).code == "pending"
    assert bot.reviews.opened == [(1, "sso_status", None)]
    member = await repo.get_member(1)
    assert member is not None and member.status == "unverified"


async def test_microsoft_login_can_be_hidden_from_moderators(repo: Repo, cfg: AppConfig) -> None:
    hidden = cfg.model_copy(update={"microsoft": cfg.microsoft.model_copy(update={"show_login_to_moderators": False})})
    bot = FakeBot(repo, hidden)
    await complete_ms(bot, 1, S1, None)
    assert bot.reviews.logins == [None]


async def test_microsoft_unmatched_can_default_to_student(repo: Repo, cfg: AppConfig) -> None:
    lenient = cfg.model_copy(update={"microsoft": cfg.microsoft.model_copy(update={"unmatched": "student"})})
    bot = FakeBot(repo, lenient)
    assert await complete_ms(bot, 1, S1, None) == Outcome("verified", "student", False)


async def test_microsoft_login_never_removes_a_status(bot: FakeBot, repo: Repo) -> None:
    await repo.set_member_status(1, status="student", method="microsoft", now=100, valid_until=200)
    assert await complete_ms(bot, 1, S1, "employee") == Outcome("verified", "student", True)
    member = await repo.get_member(1)
    assert member is not None and member.status == "student"


async def test_microsoft_login_keeps_an_already_confirmed_status(bot: FakeBot, repo: Repo) -> None:
    await repo.set_member_status(1, status="applicant", method="manual", now=100, valid_until=200)
    assert await complete_ms(bot, 1, S1, None) == Outcome("verified", "applicant", False)
    assert bot.reviews.opened == []


async def test_same_account_via_stu_and_microsoft_cannot_verify_two_members(bot: FakeBot) -> None:
    await complete(bot, 1, S1, "student")
    assert (await complete_ms(bot, 2, S1)).code == "conflict"


async def test_microsoft_login_keeps_affiliations_from_stu_login(bot: FakeBot, repo: Repo) -> None:
    await complete(bot, 1, S1, "student", "member")
    await complete_ms(bot, 1, S1)
    identity = await repo.get_identity_by_user(1)
    assert identity is not None and identity.affiliations == ["member", "student"]


async def test_create_link(bot: FakeBot, repo: Repo) -> None:
    url = await service(bot).create_link(5)
    assert url.startswith("https://verify.test/v?t=")
