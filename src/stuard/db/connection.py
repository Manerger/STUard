from __future__ import annotations

from pathlib import Path

import aiosqlite


async def connect(path: Path | str) -> aiosqlite.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Autocommit mode; multi-statement work uses explicit BEGIN IMMEDIATE via Repo.transaction().
    conn = await aiosqlite.connect(str(path), isolation_level=None)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    return conn
