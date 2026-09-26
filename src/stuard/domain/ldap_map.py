"""Parse a STU directory (LDAP) person record and map it to a status. Pure and client-agnostic.

The bot only ever reads the record of the login the user is verifying, and identity ownership is proved by the
email code, not by this lookup. Faculty is not a real attribute — it is inferred from the ``host`` /
``accountStatus`` service-entitlement entries (``mtf-stud``, ``ADmtf``); ``employeeType`` (student/staff) is real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stuard.config import EmailCfg
from stuard.domain.mapping import MappingResult

# A service entitlement like "mtf-stud" / "fei-zam" → faculty "mtf" / "fei"; "ADmtf" → "mtf".
_FACULTY = re.compile(r"^([a-z]{2,6})-(?:stud|zam|ext|dokt|phd)$")
_AD = re.compile(r"^ad([a-z]{2,6})$")
_AIS_ID = re.compile(r"^\d{1,12}$")


@dataclass(frozen=True, slots=True)
class LdapPerson:
    login: str | None
    ais_id: str | None  # numeric AIS ID (uisId) — matches the Microsoft/SAML identity fingerprint
    email: str | None
    employee_type: str | None
    faculties: frozenset[str]  # lowercase, e.g. {"mtf"}
    student_active: bool


def _lower_keys(attrs: dict[str, object]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, value in attrs.items():
        values = value if isinstance(value, list | tuple) else [value]
        out[key.lower()] = [str(v).strip() for v in values if str(v).strip()]
    return out


def _faculties(values: list[str]) -> frozenset[str]:
    found: set[str] = set()
    for value in values:
        base = value.split(":", 1)[0].strip().lower()  # "mtf-stud:active" → "mtf-stud"
        match = _FACULTY.match(base) or _AD.match(base)
        if match:
            found.add(match.group(1))
    return frozenset(found)


def parse_person(attrs: dict[str, object]) -> LdapPerson:
    a = _lower_keys(attrs)
    first = lambda key: (a.get(key) or [None])[0]  # noqa: E731
    services = a.get("host", []) + a.get("accountstatus", [])
    ais = first("uisid")
    emails = a.get("mail", [])
    return LdapPerson(
        login=first("uid"),
        ais_id=ais if ais and _AIS_ID.match(ais) else None,
        email=emails[0] if emails else None,
        employee_type=first("employeetype"),
        faculties=_faculties(services),
        student_active=any(v.strip().lower() == "student:active" for v in a.get("accountstatus", [])),
    )


def map_ldap_person(person: LdapPerson, cfg: EmailCfg) -> MappingResult:
    """Faculty gate + employeeType → status. Vyučujúci is never assigned automatically (always a review)."""
    value = (person.employee_type or "").strip().lower()
    is_student = bool(value and value in {t.lower() for t in cfg.student_types})
    if cfg.allowed_faculties:
        allowed = {f.lower() for f in cfg.allowed_faculties}
        if not (person.faculties & allowed):
            # Another faculty: a real STU student still gets in as Outsider; anyone else is rejected.
            if is_student:
                return MappingResult("outsider", False, None, False, False)
            return MappingResult(None, False, None, False, True)  # rejected
    if is_student:
        return MappingResult("student", False, None, False, False)
    if value and value in {t.lower() for t in cfg.teacher_types}:
        return MappingResult(None, False, None, True, False)  # teacher review
    if cfg.unmatched == "student":
        return MappingResult("student", False, None, False, False)
    return MappingResult(None, True, None, False, False)  # manual review
