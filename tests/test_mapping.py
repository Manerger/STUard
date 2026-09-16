from __future__ import annotations

import pytest

from stuard.config import AppConfig
from stuard.domain.mapping import (
    ScopeError,
    map_affiliations,
    map_employee_type,
    normalize_affiliations,
    scope_allowed,
)


def affs(*values: str) -> frozenset[str]:
    return frozenset(values)


def test_student(cfg: AppConfig) -> None:
    result = map_affiliations(affs("student", "member"), cfg.sso)
    assert result.status == "student"
    assert not result.review and not result.teacher_candidate and not result.rejected


def test_phd_student_who_is_also_employee(cfg: AppConfig) -> None:
    result = map_affiliations(affs("student", "employee", "member"), cfg.sso)
    assert result.status == "student"
    assert result.teacher_candidate


def test_alum(cfg: AppConfig) -> None:
    assert map_affiliations(affs("alum"), cfg.sso).status == "alumni"


def test_affiliate_goes_to_review_with_applicant_suggestion(cfg: AppConfig) -> None:
    result = map_affiliations(affs("affiliate"), cfg.sso)
    assert result.status is None
    assert result.review and result.suggest == "applicant"


def test_staff_only_is_teacher_candidate_without_status(cfg: AppConfig) -> None:
    result = map_affiliations(affs("staff", "member"), cfg.sso)
    assert result.status is None
    assert result.teacher_candidate and not result.review


def test_unmatched_review_or_reject(cfg: AppConfig) -> None:
    assert map_affiliations(affs("member"), cfg.sso).review
    strict = cfg.sso.model_copy(update={"unmatched": "reject"})
    assert map_affiliations(affs("member"), strict).rejected


@pytest.mark.parametrize(
    ("scope", "allowed"),
    [("stuba.sk", True), ("STUBA.SK", True), ("mtf.stuba.sk", True), ("notstuba.sk", False), ("evil.sk", False)],
)
def test_scope_allowed(scope: str, allowed: bool) -> None:
    assert scope_allowed(scope, ["stuba.sk"]) is allowed


def test_normalize_affiliations() -> None:
    values = normalize_affiliations(["Student@stuba.sk", "member@stuba.sk"], ["EMPLOYEE"], ["stuba.sk"])
    assert values == {"student", "member", "employee"}


@pytest.mark.parametrize("bad", ["student@evil.sk", "student", "@stuba.sk", "student@notstuba.sk"])
def test_normalize_rejects_foreign_or_malformed_scope(bad: str) -> None:
    with pytest.raises(ScopeError):
        normalize_affiliations([bad], [], ["stuba.sk"])


def test_microsoft_student_type(cfg: AppConfig) -> None:
    assert map_employee_type("student", cfg.microsoft).status == "student"
    assert map_employee_type(" Student ", cfg.microsoft).status == "student"


def test_microsoft_employee_type_needs_teacher_review(cfg: AppConfig) -> None:
    result = map_employee_type("employee", cfg.microsoft)
    assert result.status is None and result.teacher_candidate and not result.review


@pytest.mark.parametrize("employee_type", [None, "", "contractor"])
def test_microsoft_unknown_or_missing_type_goes_to_review(cfg: AppConfig, employee_type: str | None) -> None:
    result = map_employee_type(employee_type, cfg.microsoft)
    assert result.status is None and result.review and not result.teacher_candidate


def test_microsoft_unmatched_can_default_to_student(cfg: AppConfig) -> None:
    lenient = cfg.microsoft.model_copy(update={"unmatched": "student"})
    assert map_employee_type(None, lenient).status == "student"
    assert map_employee_type("employee", lenient).teacher_candidate  # teachers still need a moderator
