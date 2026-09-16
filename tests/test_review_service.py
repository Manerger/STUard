from __future__ import annotations

import asyncio

from stuard import texts as T
from stuard.config import AppConfig
from stuard.db.repos import Repo
from stuard.services.review import ReviewService
from stuard.timeutil import now_ts
from tests.fakes import FakeBot


def make(repo: Repo, cfg: AppConfig) -> tuple[FakeBot, ReviewService]:
    bot = FakeBot(repo, cfg)
    return bot, ReviewService(bot)  # type: ignore[arg-type]


async def test_two_moderators_clicking_at_once(repo: Repo, cfg: AppConfig) -> None:
    bot, service = make(repo, cfg)
    review_id = await repo.create_review(5, "manual", now_ts(), claimed_role="student")
    assert review_id is not None
    review = await repo.get_review(review_id)
    assert review is not None
    results = await asyncio.gather(
        service.decide(review, 9, approved_role="student", reason=None),
        service.decide(review, 10, approved_role=None, reason="rozmazané"),
    )
    assert results.count(T.REVIEW_ALREADY_DECIDED) == 1
    assert len(bot.dms) == 1


async def test_approve_student(repo: Repo, cfg: AppConfig) -> None:
    bot, service = make(repo, cfg)
    review_id = await repo.create_review(5, "manual", now_ts(), claimed_role="student")
    review = await repo.get_review(review_id or 0)
    assert review is not None
    await service.decide(review, 9, approved_role="student", reason=None)
    member = await repo.get_member(5)
    assert member is not None and (member.status, member.method) == ("student", "manual")
    assert member.valid_until is not None
    assert bot.roles.synced == [5]
    assert "Študent" in bot.dms[0][1] and "/profile" in bot.dms[0][1]
    assert "review_approved" in bot.audit.actions


async def test_teacher_approval_only_sets_teacher_flag(repo: Repo, cfg: AppConfig) -> None:
    _, service = make(repo, cfg)
    review_id = await repo.create_review(5, "sso_teacher", now_ts(), claimed_role="teacher", sso_affiliations=["staff"])
    review = await repo.get_review(review_id or 0)
    assert review is not None
    await service.decide(review, 9, approved_role="teacher", reason=None)
    member = await repo.get_member(5)
    assert member is not None and member.is_teacher and member.status == "unverified"


async def test_reject_sends_reason(repo: Repo, cfg: AppConfig) -> None:
    bot, service = make(repo, cfg)
    review_id = await repo.create_review(5, "manual", now_ts(), claimed_role="student")
    review = await repo.get_review(review_id or 0)
    assert review is not None
    await service.decide(review, 9, approved_role=None, reason="nečitateľná snímka")
    assert await repo.get_member(5) is None
    assert "nečitateľná snímka" in bot.dms[0][1]
    decided = await repo.get_review(review.id)
    assert decided is not None and decided.status == "rejected" and decided.decided_by == 9


async def test_expire_old_pending_reviews(repo: Repo, cfg: AppConfig) -> None:
    bot, service = make(repo, cfg)
    old = await repo.create_review(5, "manual", now_ts() - 8 * 86_400, claimed_role="student")
    fresh = await repo.create_review(6, "manual", now_ts(), claimed_role="student")
    assert await service.expire_pending() == 1
    expired, pending = await repo.get_review(old or 0), await repo.get_review(fresh or 0)
    assert expired is not None and expired.status == "expired"
    assert pending is not None and pending.status == "pending"
    assert [user for user, _ in bot.dms] == [5]
