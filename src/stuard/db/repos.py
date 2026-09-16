"""All SQL lives here. Writes are serialized with an asyncio lock on the single connection."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import aiosqlite

from stuard.domain.roleplan import StudySel

ACTIVE_FLOW_STATUSES: tuple[str, ...] = ("issued", "opened", "oauth_ok", "idp_sent", "idp_ok")
_FLOW_FIELDS = {
    "oauth_state_hash",
    "complete_token_hash",
    "relay_state",
    "saml_request_id",
    "nonce_hash",
    "pkce_verifier",
    "result",
    "error_code",
}
FlowLookup = Literal["browser_token_hash", "oauth_state_hash", "complete_token_hash", "relay_state"]
_FLOW_LOOKUPS: tuple[str, ...] = ("browser_token_hash", "oauth_state_hash", "complete_token_hash", "relay_state")


def _marks(values: Sequence[Any]) -> str:
    return ",".join("?" * len(values))


@dataclass(frozen=True, slots=True)
class MemberRow:
    user_id: int
    status: str
    is_teacher: bool
    method: str | None
    verified_at: int | None
    valid_until: int | None
    status_changed_at: int | None
    left_at: int | None


@dataclass(frozen=True, slots=True)
class IdentityRow:
    subject_hmac: bytes
    user_id: int
    affiliations: list[str]
    bound_at: int
    last_verified_at: int


@dataclass(frozen=True, slots=True)
class FlowRow:
    id: int
    user_id: int
    method: str
    link_token_hash: bytes
    browser_token_hash: bytes | None
    oauth_state_hash: bytes | None
    complete_token_hash: bytes | None
    relay_state: str | None
    saml_request_id: str | None
    nonce_hash: bytes | None
    pkce_verifier: str | None
    status: str
    result: str | None
    error_code: str | None
    created_at: int
    expires_at: int


@dataclass(frozen=True, slots=True)
class ReviewRow:
    id: int
    user_id: int
    source: str
    claimed_role: str | None
    sso_affiliations: list[str] | None
    note: str | None
    status: str
    channel_id: int | None
    message_id: int | None
    decided_by: int | None
    decided_role: str | None
    reason: str | None
    created_at: int
    decided_at: int | None


def _member(row: aiosqlite.Row) -> MemberRow:
    data = dict(row)
    data["is_teacher"] = bool(data["is_teacher"])
    return MemberRow(**data)


def _identity(row: aiosqlite.Row) -> IdentityRow:
    data = dict(row)
    data["affiliations"] = json.loads(data["affiliations"])
    return IdentityRow(**data)


def _review(row: aiosqlite.Row) -> ReviewRow:
    data = dict(row)
    data["sso_affiliations"] = json.loads(data["sso_affiliations"]) if data["sso_affiliations"] else None
    return ReviewRow(**data)


BindResult = Literal["ok", "conflict", "tombstoned"]


class Repo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self.conn.close()

    # ------------------------------------------------------------------ helpers
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._lock:
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                await self.conn.execute("ROLLBACK")
                raise
            else:
                await self.conn.execute("COMMIT")

    async def _write(self, sql: str, params: Iterable[Any] = ()) -> int:
        async with self._lock:
            cur = await self.conn.execute(sql, tuple(params))
            count = cur.rowcount
            await cur.close()
            return count

    async def _write_returning(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self._lock:
            async with self.conn.execute(sql, tuple(params)) as cur:
                return await cur.fetchone()

    async def _one(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return list(await cur.fetchall())

    # ------------------------------------------------------------------ members
    async def get_member(self, user_id: int) -> MemberRow | None:
        row = await self._one("SELECT * FROM members WHERE user_id = ?", (user_id,))
        return _member(row) if row else None

    async def ensure_member(self, user_id: int) -> None:
        await self._write("INSERT OR IGNORE INTO members(user_id) VALUES (?)", (user_id,))

    async def set_member_status(
        self,
        user_id: int,
        *,
        status: str,
        method: str | None,
        now: int,
        valid_until: int | None,
        mark_verified: bool = True,
    ) -> None:
        await self._write(
            """
            INSERT INTO members(user_id, status, method, verified_at, valid_until, status_changed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              status = excluded.status,
              method = COALESCE(excluded.method, members.method),
              verified_at = COALESCE(excluded.verified_at, members.verified_at),
              valid_until = excluded.valid_until,
              status_changed_at = CASE WHEN members.status = excluded.status
                                       THEN members.status_changed_at ELSE excluded.status_changed_at END
            """,
            (user_id, status, method, now if mark_verified else None, valid_until, now),
        )

    async def set_teacher(self, user_id: int, is_teacher: bool) -> None:
        await self._write(
            "INSERT INTO members(user_id, is_teacher) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET is_teacher = excluded.is_teacher",
            (user_id, int(is_teacher)),
        )

    async def set_left_at(self, user_id: int, left_at: int | None) -> None:
        await self._write("UPDATE members SET left_at = ? WHERE user_id = ?", (left_at, user_id))

    async def all_members(self) -> list[MemberRow]:
        return [_member(r) for r in await self._all("SELECT * FROM members")]

    async def members_with_deadline(self, statuses: Sequence[str]) -> list[MemberRow]:
        if not statuses:
            return []
        rows = await self._all(
            f"SELECT * FROM members WHERE valid_until IS NOT NULL AND status IN ({_marks(statuses)})",  # noqa: S608
            statuses,
        )
        return [_member(r) for r in rows]

    async def left_members_before(self, ts: int) -> list[int]:
        rows = await self._all("SELECT user_id FROM members WHERE left_at IS NOT NULL AND left_at < ?", (ts,))
        return [int(r["user_id"]) for r in rows]

    async def delete_member(self, user_id: int) -> None:
        async with self.transaction() as c:
            await c.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
            await c.execute("DELETE FROM review_requests WHERE user_id = ?", (user_id,))
            await c.execute("DELETE FROM verify_flows WHERE user_id = ?", (user_id,))
            await c.execute("DELETE FROM members WHERE user_id = ?", (user_id,))  # cascades identity + study

    # ------------------------------------------------------------------ identities
    async def get_identity_by_subject(self, subject: bytes) -> IdentityRow | None:
        row = await self._one("SELECT * FROM identities WHERE subject_hmac = ?", (subject,))
        return _identity(row) if row else None

    async def get_identity_by_user(self, user_id: int) -> IdentityRow | None:
        row = await self._one("SELECT * FROM identities WHERE user_id = ?", (user_id,))
        return _identity(row) if row else None

    async def bind_identity(self, subject: bytes, user_id: int, affiliations: Iterable[str], now: int) -> BindResult:
        """Atomically bind a UIS identity to a Discord user, refusing accounts bound elsewhere."""
        affs = json.dumps(sorted(affiliations))
        async with self.transaction() as c:
            async with c.execute(
                "SELECT 1 FROM tombstones WHERE subject_hmac = ? AND expires_at > ?", (subject, now)
            ) as cur:
                if await cur.fetchone():
                    return "tombstoned"
            async with c.execute("SELECT user_id FROM identities WHERE subject_hmac = ?", (subject,)) as cur:
                row = await cur.fetchone()
            if row is not None and int(row["user_id"]) != user_id:
                return "conflict"
            await c.execute("INSERT OR IGNORE INTO members(user_id) VALUES (?)", (user_id,))
            await c.execute("DELETE FROM identities WHERE user_id = ? AND subject_hmac != ?", (user_id, subject))
            await c.execute(
                """
                INSERT INTO identities(subject_hmac, user_id, affiliations, bound_at, last_verified_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(subject_hmac) DO UPDATE SET
                  affiliations = CASE WHEN excluded.affiliations = '[]'
                                      THEN identities.affiliations ELSE excluded.affiliations END,
                  last_verified_at = excluded.last_verified_at
                """,
                (subject, user_id, affs, now, now),
            )
        return "ok"

    async def unbind_user(self, user_id: int) -> bool:
        return await self._write("DELETE FROM identities WHERE user_id = ?", (user_id,)) > 0

    async def add_tombstone(self, subject: bytes, expires_at: int) -> None:
        await self._write(
            "INSERT INTO tombstones(subject_hmac, expires_at) VALUES (?, ?) "
            "ON CONFLICT(subject_hmac) DO UPDATE SET expires_at = excluded.expires_at",
            (subject, expires_at),
        )

    async def purge_tombstones(self, now: int) -> int:
        return await self._write("DELETE FROM tombstones WHERE expires_at <= ?", (now,))

    # ------------------------------------------------------------------ verification flows
    async def create_flow(self, user_id: int, link_token_hash: bytes, now: int, ttl: int) -> int:
        """Create a flow; any still-active flow of the same user is superseded."""
        async with self.transaction() as c:
            await c.execute(
                f"UPDATE verify_flows SET status = 'superseded' "  # noqa: S608
                f"WHERE user_id = ? AND status IN ({_marks(ACTIVE_FLOW_STATUSES)})",
                (user_id, *ACTIVE_FLOW_STATUSES),
            )
            cur = await c.execute(
                "INSERT INTO verify_flows(user_id, link_token_hash, status, created_at, expires_at) "
                "VALUES (?, ?, 'issued', ?, ?)",
                (user_id, link_token_hash, now, now + ttl),
            )
            flow_id = int(cur.lastrowid or 0)
            await cur.close()
        return flow_id

    async def open_flow(
        self, link_token_hash: bytes, browser_token_hash: bytes, now: int, ttl: int, method: str = "saml"
    ) -> FlowRow | None:
        """Consume a link token exactly once, fix the login method and bind the flow to a browser cookie."""
        row = await self._write_returning(
            "UPDATE verify_flows SET status = 'opened', method = ?, browser_token_hash = ?, expires_at = ? "
            "WHERE link_token_hash = ? AND status = 'issued' AND expires_at > ? RETURNING *",
            (method, browser_token_hash, now + ttl, link_token_hash, now),
        )
        return FlowRow(**dict(row)) if row else None

    async def get_flow(self, flow_id: int) -> FlowRow | None:
        row = await self._one("SELECT * FROM verify_flows WHERE id = ?", (flow_id,))
        return FlowRow(**dict(row)) if row else None

    async def get_flow_by(self, column: FlowLookup, value: Any) -> FlowRow | None:
        if column not in _FLOW_LOOKUPS:
            raise ValueError(column)
        row = await self._one(f"SELECT * FROM verify_flows WHERE {column} = ?", (value,))  # noqa: S608
        return FlowRow(**dict(row)) if row else None

    async def transition_flow(
        self, flow_id: int, from_status: str | Sequence[str], to_status: str, now: int, **fields: Any
    ) -> bool:
        """Compare-and-set a flow status. Returns False if the flow moved on, expired or does not exist."""
        froms = (from_status,) if isinstance(from_status, str) else tuple(from_status)
        sets, params = ["status = ?"], [to_status]
        for name, value in fields.items():
            if name not in _FLOW_FIELDS:
                raise ValueError(f"unknown flow field {name}")
            sets.append(f"{name} = ?")
            params.append(value)
        sql = (
            f"UPDATE verify_flows SET {', '.join(sets)} "  # noqa: S608
            f"WHERE id = ? AND status IN ({_marks(froms)}) AND expires_at > ?"
        )
        return await self._write(sql, (*params, flow_id, *froms, now)) == 1

    async def fail_flow(self, flow_id: int, error_code: str) -> None:
        await self._write(
            f"UPDATE verify_flows SET status = 'failed', error_code = ? "  # noqa: S608
            f"WHERE id = ? AND status IN ({_marks(ACTIVE_FLOW_STATUSES)})",
            (error_code, flow_id, *ACTIVE_FLOW_STATUSES),
        )

    async def purge_flows(self, created_before: int) -> int:
        return await self._write("DELETE FROM verify_flows WHERE created_at < ?", (created_before,))

    async def record_assertion(self, assertion_id: str, expires_at: int) -> bool:
        """False if this assertion ID was already used (replay)."""
        try:
            await self._write(
                "INSERT INTO saml_seen_assertions(assertion_id, expires_at) VALUES (?, ?)", (assertion_id, expires_at)
            )
        except sqlite3.IntegrityError:
            return False
        return True

    async def purge_assertions(self, now: int) -> int:
        return await self._write("DELETE FROM saml_seen_assertions WHERE expires_at <= ?", (now,))

    # ------------------------------------------------------------------ reviews
    async def create_review(
        self,
        user_id: int,
        source: str,
        now: int,
        *,
        claimed_role: str | None = None,
        sso_affiliations: Iterable[str] | None = None,
        note: str | None = None,
    ) -> int | None:
        """None if the user already has a pending review from the same source."""
        affs = json.dumps(sorted(sso_affiliations)) if sso_affiliations is not None else None
        try:
            async with self._lock:
                cur = await self.conn.execute(
                    "INSERT INTO review_requests(user_id, source, claimed_role, sso_affiliations, note, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, source, claimed_role, affs, note, now),
                )
                review_id = int(cur.lastrowid or 0)
                await cur.close()
        except sqlite3.IntegrityError:
            return None
        return review_id

    async def set_review_message(self, review_id: int, channel_id: int, message_id: int) -> None:
        await self._write(
            "UPDATE review_requests SET channel_id = ?, message_id = ? WHERE id = ?",
            (channel_id, message_id, review_id),
        )

    async def get_review(self, review_id: int) -> ReviewRow | None:
        row = await self._one("SELECT * FROM review_requests WHERE id = ?", (review_id,))
        return _review(row) if row else None

    async def pending_review(self, user_id: int, source: str) -> ReviewRow | None:
        row = await self._one(
            "SELECT * FROM review_requests WHERE user_id = ? AND source = ? AND status = 'pending'", (user_id, source)
        )
        return _review(row) if row else None

    async def pending_reviews(self, limit: int = 25) -> list[ReviewRow]:
        rows = await self._all(
            "SELECT * FROM review_requests WHERE status = 'pending' ORDER BY created_at LIMIT ?", (limit,)
        )
        return [_review(r) for r in rows]

    async def reviews_for_user(self, user_id: int) -> list[ReviewRow]:
        rows = await self._all("SELECT * FROM review_requests WHERE user_id = ? ORDER BY created_at", (user_id,))
        return [_review(r) for r in rows]

    async def last_decision_at(self, user_id: int, source: str, status: str) -> int | None:
        row = await self._one(
            "SELECT MAX(decided_at) AS ts FROM review_requests WHERE user_id = ? AND source = ? AND status = ?",
            (user_id, source, status),
        )
        return int(row["ts"]) if row and row["ts"] is not None else None

    async def count_reviews_since(self, user_id: int, source: str, since: int) -> int:
        row = await self._one(
            "SELECT COUNT(*) AS n FROM review_requests WHERE user_id = ? AND source = ? AND created_at >= ?",
            (user_id, source, since),
        )
        return int(row["n"]) if row else 0

    async def decide_review(
        self,
        review_id: int,
        *,
        status: str,
        decided_by: int | None,
        now: int,
        decided_role: str | None = None,
        reason: str | None = None,
    ) -> bool:
        """Compare-and-set pending → decided. False if someone else decided first."""
        return (
            await self._write(
                "UPDATE review_requests SET status = ?, decided_by = ?, decided_role = ?, reason = ?, decided_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, decided_by, decided_role, reason, now, review_id),
            )
            == 1
        )

    async def pending_reviews_before(self, created_before: int) -> list[ReviewRow]:
        rows = await self._all(
            "SELECT * FROM review_requests WHERE status = 'pending' AND created_at < ?", (created_before,)
        )
        return [_review(r) for r in rows]

    async def purge_decided_reviews(self, decided_before: int) -> int:
        return await self._write(
            "DELETE FROM review_requests WHERE status != 'pending' AND decided_at < ?", (decided_before,)
        )

    # ------------------------------------------------------------------ study selection
    async def get_study(self, user_id: int) -> StudySel | None:
        row = await self._one("SELECT degree, programme_id, year FROM study_selection WHERE user_id = ?", (user_id,))
        return StudySel(row["degree"], row["programme_id"], int(row["year"])) if row else None

    async def set_study(self, user_id: int, study: StudySel, now: int) -> None:
        async with self.transaction() as c:
            await c.execute("INSERT OR IGNORE INTO members(user_id) VALUES (?)", (user_id,))
            await c.execute(
                """
                INSERT INTO study_selection(user_id, degree, programme_id, year, updated_at) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  degree = excluded.degree, programme_id = excluded.programme_id,
                  year = excluded.year, updated_at = excluded.updated_at
                """,
                (user_id, study.degree, study.programme_id, study.year, now),
            )

    async def clear_study(self, user_id: int) -> None:
        await self._write("DELETE FROM study_selection WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------------ role map
    async def role_map(self) -> dict[str, int]:
        return {r["key"]: int(r["role_id"]) for r in await self._all("SELECT key, role_id FROM role_map")}

    async def set_role_mapping(self, key: str, role_id: int) -> None:
        await self._write(
            "INSERT INTO role_map(key, role_id) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET role_id = excluded.role_id",
            (key, role_id),
        )

    # ------------------------------------------------------------------ reminders
    async def sent_reminders(self, user_id: int, cycle: str) -> set[str]:
        rows = await self._all("SELECT kind FROM reminders WHERE user_id = ? AND cycle = ?", (user_id, cycle))
        return {r["kind"] for r in rows}

    async def record_reminders(self, user_id: int, cycle: str, kinds: Iterable[str], now: int) -> None:
        async with self.transaction() as c:
            for kind in kinds:
                await c.execute(
                    "INSERT OR IGNORE INTO reminders(user_id, cycle, kind, sent_at) VALUES (?, ?, ?, ?)",
                    (user_id, cycle, kind, now),
                )

    # ------------------------------------------------------------------ audit
    async def add_audit(
        self, ts: int, action: str, actor_id: int | None, target_id: int | None, detail: dict[str, Any] | None
    ) -> None:
        await self._write(
            "INSERT INTO audit(ts, actor_id, target_id, action, detail) VALUES (?, ?, ?, ?, ?)",
            (ts, actor_id, target_id, action, json.dumps(detail, ensure_ascii=False) if detail else None),
        )

    async def audit_for_user(self, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._all(
            "SELECT ts, action, detail FROM audit WHERE target_id = ? ORDER BY ts DESC LIMIT ?", (user_id, limit)
        )
        return [dict(r) for r in rows]

    async def purge_audit(self, before: int) -> int:
        return await self._write("DELETE FROM audit WHERE ts < ?", (before,))

    # ------------------------------------------------------------------ settings
    async def get_setting(self, key: str) -> str | None:
        row = await self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return str(row["value"]) if row else None

    async def set_setting(self, key: str, value: str | None) -> None:
        if value is None:
            await self._write("DELETE FROM settings WHERE key = ?", (key,))
        else:
            await self._write(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
