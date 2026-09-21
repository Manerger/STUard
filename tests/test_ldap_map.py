from __future__ import annotations

from stuard.config import AppConfig
from stuard.domain.ldap_map import map_ldap_person, parse_person

# The real MTF student record shape (from an anonymous ldapsearch of the user's own entry).
MTF_STUDENT = {
    "uid": ["xpodhorec"],
    "uisId": ["150309"],
    "cn": ["Filip Podhorec"],
    "employeeType": ["student"],
    "mail": ["xpodhorec@stuba.sk"],
    "host": ["webmail", "ADmtf", "mtf-stud", "webkredit", "uis", "office365", "student", "wifi", "vpn"],
    "accountStatus": [
        "wifi:active", "student:active", "ADmtf:active", "webkredit:active", "vpn:active",
        "office365:active", "uis:active", "webmail:active", "mtf-stud:active",
    ],
}


def test_parse_real_student_record() -> None:
    p = parse_person(MTF_STUDENT)
    assert p.login == "xpodhorec"
    assert p.ais_id == "150309"
    assert p.email == "xpodhorec@stuba.sk"
    assert p.employee_type == "student"
    assert p.faculties == frozenset({"mtf"})
    assert p.student_active is True


def test_case_insensitive_attribute_keys() -> None:
    # ldap3 may return attribute names in any case; parsing must not care.
    p = parse_person({"UID": "xtest", "UISID": "222", "EMPLOYEETYPE": "student", "HOST": ["mtf-stud"]})
    assert p.login == "xtest" and p.ais_id == "222" and p.faculties == frozenset({"mtf"})


def test_mtf_student_maps_to_student(cfg: AppConfig) -> None:
    result = map_ldap_person(parse_person(MTF_STUDENT), cfg.email)
    assert result.status == "student" and not result.rejected and not result.review


def test_other_faculty_is_rejected(cfg: AppConfig) -> None:
    fei = {"uid": ["xfei"], "employeeType": ["student"], "host": ["fei-stud"], "accountStatus": ["fei-stud:active"]}
    result = map_ldap_person(parse_person(fei), cfg.email)
    assert result.rejected is True  # allowed_faculties = [MTF]


def test_staff_gets_teacher_review_never_auto(cfg: AppConfig) -> None:
    staff = {"uid": ["xstaff"], "employeeType": ["employee"], "host": ["mtf-zam"], "accountStatus": ["mtf-zam:active"]}
    result = map_ldap_person(parse_person(staff), cfg.email)
    assert result.status is None and result.teacher_candidate is True


def test_unknown_type_goes_to_review(cfg: AppConfig) -> None:
    other = {"uid": ["x"], "employeeType": ["visitor"], "host": ["mtf-stud"]}
    result = map_ldap_person(parse_person(other), cfg.email)
    assert result.review is True and result.status is None


def test_faculty_gate_can_be_disabled(cfg: AppConfig) -> None:
    lenient = cfg.email.model_copy(update={"allowed_faculties": []})
    fei = {"uid": ["xfei"], "employeeType": ["student"], "host": ["fei-stud"]}
    result = map_ldap_person(parse_person(fei), lenient)
    assert result.status == "student"
