"""Forward-only SQL migrations tracked with PRAGMA user_version."""

from __future__ import annotations

import logging
from importlib import resources

import aiosqlite

log = logging.getLogger(__name__)


def _migrations() -> list[tuple[int, str, str]]:
    folder = resources.files("stuard.db") / "migrations"
    found = []
    for entry in folder.iterdir():
        if entry.name.endswith(".sql"):
            number = int(entry.name.split("_", 1)[0])
            found.append((number, entry.name, entry.read_text(encoding="utf-8")))
    return sorted(found)


async def migrate(conn: aiosqlite.Connection) -> int:
    async with conn.execute("PRAGMA user_version") as cur:
        row = await cur.fetchone()
    version = int(row[0]) if row else 0
    for number, name, sql in _migrations():
        if number <= version:
            continue
        log.info("applying migration %s", name)
        try:
            await conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                await conn.execute("ROLLBACK")
            raise
        version = number
    return version
