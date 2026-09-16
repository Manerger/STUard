from __future__ import annotations

from stuard.config import AppConfig
from stuard.domain.roleplan import StudySel, plan_changes, role_specs, target_role_keys


def test_role_specs_use_the_servers_year_role_names(cfg: AppConfig) -> None:
    specs = role_specs(cfg)
    assert specs["student"].name == "Študent"
    assert [specs[f"year:bc:{y}"].name for y in (1, 2, 3)] == ["1-BC", "2-BC", "3-BC"]
    assert [specs[f"year:ing:{y}"].name for y in (1, 2)] == ["1-ing", "2-ing"]
    assert specs["year:phd:4"].name == "4-PhD"
    assert "year:ing:3" not in specs
    assert "degree:bc" not in specs  # year roles already carry the degree
    assert specs["programme:bc-mech"].name == "Bc. Mechatronika"
    assert "programme:phd-iiar-en" not in specs  # shares the SK role
    assert all(len(s.name) <= 100 for s in specs.values())


def test_student_with_study(cfg: AppConfig) -> None:
    keys = target_role_keys("student", False, StudySel("bc", "bc-mech", 2), cfg)
    assert keys == {"student", "verified", "programme:bc-mech", "year:bc:2"}


def test_degree_roles_can_be_enabled(cfg: AppConfig) -> None:
    names = cfg.study.role_names.model_copy(update={"degree": "{degree}"})
    with_degrees = cfg.model_copy(update={"study": cfg.study.model_copy(update={"role_names": names})})
    assert role_specs(with_degrees)["degree:bc"].name == "Bc."
    assert "degree:bc" in target_role_keys("student", False, StudySel("bc", "bc-mech", 2), with_degrees)


def test_english_programme_uses_group_role(cfg: AppConfig) -> None:
    keys = target_role_keys("student", False, StudySel("phd", "phd-iiar-en", 4), cfg)
    assert "programme:phd-piar" in keys


def test_former_student_loses_study_roles_but_stays_verified(cfg: AppConfig) -> None:
    keys = target_role_keys("former_student", False, StudySel("bc", "bc-mech", 2), cfg)
    assert keys == {"former_student", "verified"}


def test_applicant_and_alumni_have_no_study_roles(cfg: AppConfig) -> None:
    study = StudySel("ing", "ing-mi", 1)
    assert target_role_keys("applicant", False, study, cfg) == {"applicant", "verified"}
    assert target_role_keys("alumni", False, study, cfg) == {"alumni", "verified"}


def test_teacher_without_status(cfg: AppConfig) -> None:
    assert target_role_keys("unverified", True, None, cfg) == {"teacher", "verified"}
    assert target_role_keys("unverified", False, None, cfg) == set()


def test_invalid_study_selection_is_ignored(cfg: AppConfig) -> None:
    assert target_role_keys("student", False, StudySel("ing", "ing-mi", 3), cfg) == {"student", "verified"}
    assert target_role_keys("student", False, StudySel("bc", "ing-mi", 1), cfg) == {"student", "verified"}
    assert target_role_keys("student", False, StudySel("bc", "gone", 1), cfg) == {"student", "verified"}


def test_plan_changes_never_touches_unmanaged_roles(cfg: AppConfig) -> None:
    managed = set(role_specs(cfg))
    current = {"student", "verified", "programme:bc-mech", "year:bc:2", "some-unmanaged"}
    add, remove = plan_changes(current, {"former_student", "verified"}, managed)
    assert add == {"former_student"}
    assert remove == {"student", "programme:bc-mech", "year:bc:2"}
