"""In-memory sliding-window rate limiter (single process)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

_MAX_KEYS = 50_000


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit must be >= 1 and window_seconds > 0")
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def _trim(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def hit(self, key: str) -> bool:
        """Record an attempt. Returns False when the key is over the limit (attempt not recorded)."""
        now = self._clock()
        if len(self._hits) > _MAX_KEYS:
            self.prune()
        hits = self._trim(key, now)
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str) -> float:
        now = self._clock()
        hits = self._trim(key, now)
        if len(hits) < self.limit:
            return 0.0
        return max(0.0, hits[0] + self.window - now)

    def prune(self) -> None:
        now = self._clock()
        for key in list(self._hits):
            if not self._trim(key, now):
                del self._hits[key]
