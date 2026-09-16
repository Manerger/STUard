"""Map what the login provider says about an account to member status and teacher candidacy."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from stuard.config import MicrosoftCfg, SsoCfg, Status


class ScopeError(ValueError):
    """An attribute carried a scope outside the allowed STU domains."""


def scope_allowed(scope: str, allowed_scopes: Iterable[str]) -> bool:
    scope = scope.strip().lower()
    for allowed in allowed_scopes:
        allowed = allowed.strip().lower()
        if scope == allowed or scope.endswith("." + allowed):
            return True
    return False


def normalize_affiliations(
    scoped: Iterable[str], unscoped: Iterable[str], allowed_scopes: Iterable[str]
) -> frozenset[str]:
    """Combine eduPersonScopedAffiliation and eduPersonAffiliation into bare lowercase values.

    Any scoped value from a foreign domain rejects the whole assertion.
    """
    allowed = list(allowed_scopes)
    values: set[str] = set()
    for item in scoped:
        value, sep, scope = item.strip().partition("@")
        if not sep or not value or not scope_allowed(scope, allowed):
            raise ScopeError("affiliation scope is not allowed")
        values.add(value.lower())
    for item in unscoped:
        if item.strip():
            values.add(item.strip().lower())
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class MappingResult:
    status: Status | None  # status to assign immediately
    review: bool  # a moderator must decide the status
    suggest: Status | None  # suggested status for that review
    teacher_candidate: bool  # create a (always manual) Vyučujúci review
    rejected: bool


def map_affiliations(affiliations: frozenset[str], cfg: SsoCfg) -> MappingResult:
    """idp.stuba.sk eduPersonScopedAffiliation values → status."""
    teacher = bool(affiliations & {a.lower() for a in cfg.teacher_affiliations})
    for rule in cfg.status_rules:
        if affiliations & {a.lower() for a in rule.any_of}:
            if rule.action == "assign":
                return MappingResult(rule.status, False, None, teacher, False)
            return MappingResult(None, True, rule.suggest, teacher, False)
    if teacher:
        return MappingResult(None, False, None, True, False)
    if cfg.unmatched == "reject":
        return MappingResult(None, False, None, False, True)
    return MappingResult(None, True, None, False, False)


def map_employee_type(employee_type: str | None, cfg: MicrosoftCfg) -> MappingResult:
    """Microsoft 365 employeeType (e.g. "student") → status. Vyučujúci is never assigned automatically."""
    value = (employee_type or "").strip().lower()
    if value and value in {t.lower() for t in cfg.student_types}:
        return MappingResult("student", False, None, False, False)
    if value and value in {t.lower() for t in cfg.teacher_types}:
        return MappingResult(None, False, None, True, False)
    if cfg.unmatched == "student":
        return MappingResult("student", False, None, False, False)
    return MappingResult(None, True, None, False, False)
