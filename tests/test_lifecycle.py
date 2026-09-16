from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stuard.config import ReverifyCfg
from stuard.domain.lifecycle import due_reminders, expired_status, status_after_sso, valid_until

TZ = ZoneInfo("Europe/Bratislava")
CFG = ReverifyCfg()


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=TZ)


@pytest.mark.parametrize(
    ("verified", "expected_year"),
    [
        (local(2026, 9, 15), 2026),  # before the window opens → re-verify this autumn
        (local(2026, 9, 20), 2027),  # window opening instant counts as the new cycle
        (local(2026, 9, 25), 2027),
        (local(2026, 12, 31, 23, 0), 2027),
        (local(2027, 2, 10), 2027),
    ],
)
def test_valid_until(verified: datetime, expected_year: int) -> None:
    assert valid_until(verified, CFG, TZ) == local(expected_year, 10, 31, 23, 59, 59)


def test_valid_until_accepts_utc_input() -> None:
    utc = datetime(2026, 9, 19, 22, 30, tzinfo=ZoneInfo("UTC"))  # 00:30 on 20 Sep in Bratislava
    assert valid_until(utc, CFG, TZ).year == 2027


def test_due_reminders() -> None:
    deadline = local(2026, 10, 31, 23, 59, 59)
    days = [30, 14, 3]
    assert due_reminders(local(2026, 9, 25), deadline, days, set()) == []
    assert due_reminders(local(2026, 10, 5), deadline, days, set()) == [30]
    assert due_reminders(local(2026, 10, 5), deadline, days, {30}) == []
    assert due_reminders(local(2026, 10, 29, 12), deadline, days, set()) == [3, 14, 30]
    assert due_reminders(local(2026, 10, 29, 12), deadline, days, {30}) == [3, 14]
    assert due_reminders(local(2026, 11, 1), deadline, days, set()) == []


def test_expired_status() -> None:
    assert expired_status("student", CFG) == "former_student"
    assert expired_status("applicant", CFG) == "unverified"
    assert expired_status("alumni", CFG) is None
    assert expired_status("former_student", CFG) is None


@pytest.mark.parametrize(
    ("old", "mapped", "expected"),
    [
        ("unverified", "student", "student"),
        ("applicant", "student", "student"),
        ("student", "student", "student"),
        ("student", "alumni", "alumni"),
        ("student", None, "former_student"),
        ("applicant", None, None),
        ("unverified", None, None),
    ],
)
def test_status_after_sso(old: str, mapped: str | None, expected: str | None) -> None:
    assert status_after_sso(old, mapped) == expected  # type: ignore[arg-type]
