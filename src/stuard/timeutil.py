from __future__ import annotations

import time
from datetime import UTC, datetime


def now_ts() -> int:
    return int(time.time())


def to_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


def to_ts(dt: datetime) -> int:
    return int(dt.timestamp())
