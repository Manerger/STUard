from __future__ import annotations

import asyncio

import pytest

from stuard.db.migrate import migrate
from stuard.db.repos import Repo
from stuard.domain.roleplan import StudySel
from stuard.security.tokens import hash_token


async def test_migrate_is_idempotent(repo: Repo) -> None:
    assert await migrate(repo.conn) == 1


async def test_bind_identity_conflict_and_rebind(repo: Repo) -> None:
    s1, s2 = b"a" * 32, b"b" * 32
    assert await repo.bind_identity(s1, 1, ["student"], 100) == "ok"
    assert await repo.bind_identity(s1, 2, ["student"], 101) == "conflict"
    identity = await repo.get_identity_by_subject(s1)
    assert identity is not None and identity.user_id == 1

    assert await repo.bind_identity(s1, 1, ["alum"], 102) == "ok"
    identity = await repo.get_identity_by_user(1)
    assert identity is not None and identity.affiliations == ["alum"] and identity.bound_at == 100

    # Same Discord user with a different UIS account replaces the old binding.
    assert await repo.bind_identity(s2, 1, ["student"], 103) == "ok"
    assert await repo.get_identity_by_subject(s1) is None


async def test_tombstone_blocks_binding_until_expiry(repo: Repo) -> None:
    subject = b"t" * 32
    await repo.add_tombstone(subject, expires_at=200)
    assert await repo.bind_identity(subject, 5, [], 100) == "tombstoned"
    assert await repo.bind_identity(subject, 5, [], 300) == "ok"


async def test_link_token_is_single_use_under_concurrency(repo: Repo) -> None:
    await repo.create_flow(1, hash_token("tok"), now=1000, ttl=600)
    results = await asyncio.gather(
        repo.open_flow(hash_token("tok"), b"x" * 32, 1001, 900),
        repo.open_flow(hash_token("tok"), b"y" * 32, 1001, 900),
    )
    assert sum(r is not None for r in results) == 1


async def test_expired_link_cannot_be_opened(repo: Repo) -> None:
    await repo.create_flow(1, hash_token("tok"), now=1000, ttl=600)
    assert await repo.open_flow(hash_token("tok"), b"x" * 32, 1600, 900) is None


async def test_new_flow_supersedes_previous(repo: Repo) -> None:
    await repo.create_flow(1, hash_token("a"), 1000, 600)
    await repo.create_flow(1, hash_token("b"), 1001, 600)
    assert await repo.open_flow(hash_token("a"), b"x" * 32, 1002, 900) is None
    assert await repo.open_flow(hash_token("b"), b"y" * 32, 1002, 900) is not None


async def test_transition_flow_is_compare_and_set(repo: Repo) -> None:
    await repo.create_flow(1, hash_token("tok"), 1000, 600)
    flow = await repo.open_flow(hash_token("tok"), b"x" * 32, 1001, 900)
    assert flow is not None and flow.expires_at == 1901
    assert await repo.transition_flow(flow.id, "opened", "oauth_ok", 1002)
    assert not await repo.transition_flow(flow.id, "opened", "oauth_ok", 1002)
    assert not await repo.transition_flow(flow.id, "oauth_ok", "idp_sent", now=1901)  # expired
    assert await repo.transition_flow(flow.id, "oauth_ok", "idp_sent", 1003, relay_state="r", saml_request_id="_id")
    found = await repo.get_flow_by("relay_state", "r")
    assert found is not None and found.saml_request_id == "_id"
    with pytest.raises(ValueError):
        await repo.transition_flow(flow.id, "idp_sent", "idp_ok", 1003, user_id=2)


async def test_assertion_replay_detected(repo: Repo) -> None:
    assert await repo.record_assertion("_a1", 2000)
    assert not await repo.record_assertion("_a1", 2000)


async def test_one_pending_review_per_source(repo: Repo) -> None:
    r1 = await repo.create_review(7, "manual", 100, claimed_role="student")
    assert r1 is not None
    assert await repo.create_review(7, "manual", 101) is None
    assert await repo.create_review(7, "sso_teacher", 101, sso_affiliations=["staff"]) is not None
    assert await repo.decide_review(r1, status="rejected", decided_by=9, now=102, reason="blurry")
    assert not await repo.decide_review(r1, status="approved", decided_by=10, now=103)
    assert await repo.create_review(7, "manual", 104) is not None
    assert await repo.last_decision_at(7, "manual", "rejected") == 102
    assert await repo.count_reviews_since(7, "manual", 0) == 2


async def test_member_status_and_delete_cascades(repo: Repo) -> None:
    await repo.set_member_status(1, status="student", method="sso", now=100, valid_until=500)
    await repo.set_study(1, StudySel("bc", "bc-mech", 2), 100)
    assert await repo.bind_identity(b"s" * 32, 1, ["student"], 100) == "ok"
    member = await repo.get_member(1)
    assert member is not None and member.status == "student" and member.verified_at == 100

    await repo.set_member_status(
        1, status="former_student", method=None, now=200, valid_until=None, mark_verified=False
    )
    member = await repo.get_member(1)
    assert member is not None
    assert (member.method, member.verified_at, member.status_changed_at, member.valid_until) == ("sso", 100, 200, None)

    await repo.delete_member(1)
    assert await repo.get_member(1) is None
    assert await repo.get_study(1) is None
    assert await repo.get_identity_by_user(1) is None
