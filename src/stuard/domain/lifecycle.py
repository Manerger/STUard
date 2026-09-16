"""Yearly re-verification: validity windows, reminders and status transitions."""

from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo

from stuard.config import ReverifyCfg, Status, parse_mmdd


def window_start_for_year(year: int, cfg: ReverifyCfg, tz: tzinfo) -> datetime:
    month, day = parse_mmdd(cfg.window_start)
    return datetime(year, month, day, tzinfo=tz)


def deadline_for_year(year: int, cfg: ReverifyCfg, tz: tzinfo) -> datetime:
    month, day = parse_mmdd(cfg.deadline)
    return datetime.combine(datetime(year, month, day).date(), time(23, 59, 59), tzinfo=tz)


def valid_until(verified_at: datetime, cfg: ReverifyCfg, tz: tzinfo) -> datetime:
    """Verification is valid until the deadline of the next re-verification window that has not opened yet.

    Verified before this year's window opens → re-verify by this year's deadline.
    Verified once the window is open (or later in the year) → valid until next year's deadline.
    """
    local = verified_at.astimezone(tz)
    year = local.year if local < window_start_for_year(local.year, cfg, tz) else local.year + 1
    return deadline_for_year(year, cfg, tz)


def cycle_id(valid_until_dt: datetime) -> str:
    return valid_until_dt.date().isoformat()


def due_reminders(now: datetime, valid_until_dt: datetime, days_before: list[int], sent: set[int]) -> list[int]:
    """Reminder offsets (days before the deadline) that are due now and not yet sent."""
    if now >= valid_until_dt:
        return []
    return sorted(d for d in set(days_before) if d not in sent and valid_until_dt - timedelta(days=d) <= now)


def expired_status(status: str, cfg: ReverifyCfg) -> Status | None:
    """Status to apply when the deadline passes without re-verification (None = no change)."""
    if status not in cfg.applies_to:
        return None
    new = cfg.on_expired.get(status)  # type: ignore[call-overload]
    return new if new is not None and new != status else None


def status_after_sso(old: str, mapped: Status | None) -> Status | None:
    """Status after a successful SSO login. None means "leave the status unchanged".

    A former student whose account no longer carries a mapped status loses study access.
    """
    if mapped is not None:
        return mapped
    if old == "student":
        return "former_student"
    return None
