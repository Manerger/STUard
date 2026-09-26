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
    pending = [entry for entry in _migrations() if entry[0] > version]
    if not pending:
        return version
    # Rebuilding a table (the SQLite way to change a CHECK) must not cascade-delete children, and
    # PRAGMA foreign_keys is a no-op inside a transaction, so disable enforcement around the whole run
    # and verify integrity afterwards. Restored to ON in the finally, matching the app connection.
    await conn.execute("PRAGMA foreign_keys=OFF")
    try:
        for number, name, sql in pending:
            log.info("applying migration %s", name)
            try:
                await conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
            except Exception:
                if conn.in_transaction:
                    await conn.execute("ROLLBACK")
                raise
            version = number
        async with conn.execute("PRAGMA foreign_key_check") as cur:
            violations = await cur.fetchall()
        if violations:
            raise RuntimeError(f"migration left foreign key violations: {violations}")
    finally:
        await conn.execute("PRAGMA foreign_keys=ON")
    return version
