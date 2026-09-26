"""Pure computation of which managed roles a member should have."""

from __future__ import annotations

from dataclasses import dataclass

from stuard.config import IDENTITY_ROLE_KEYS, STATUS_ROLE_KEYS, AppConfig

STUDY_KEY_PREFIXES = ("degree:", "programme:", "year:")


@dataclass(frozen=True, slots=True)
class RoleSpec:
    key: str
    name: str
    color: int | None = None
    hoist: bool = False


@dataclass(frozen=True, slots=True)
class StudySel:
    degree: str
    programme_id: str
    year: int


def degree_key(degree: str) -> str:
    return f"degree:{degree}"


def programme_key(programme_role_id: str) -> str:
    return f"programme:{programme_role_id}"


def year_key(degree: str, year: int) -> str:
    return f"year:{degree}:{year}"


def is_study_key(key: str) -> bool:
    return key.startswith(STUDY_KEY_PREFIXES)


def role_specs(cfg: AppConfig) -> dict[str, RoleSpec]:
    """Every role the bot manages, keyed by a stable key (names may be renamed in Discord)."""
    specs: dict[str, RoleSpec] = {}
    for key in IDENTITY_ROLE_KEYS:
        role = cfg.roles[key]
        specs[key] = RoleSpec(key, role.name, role.color_int, role.hoist)
    study = cfg.study
    for dkey, degree in study.degrees.items():
        degree_name = study.degree_role_name(dkey)
        if degree_name is not None:
            specs[degree_key(dkey)] = RoleSpec(degree_key(dkey), degree_name)
        for year in range(1, degree.years + 1):
            key = year_key(dkey, year)
            specs[key] = RoleSpec(key, study.year_role_name(dkey, year))
    for programme in study.programmes:
        if programme.role_group is None:
            key = programme_key(programme.id)
            specs[key] = RoleSpec(key, study.programme_role_name(programme))
    return specs


def valid_study(study: StudySel | None, cfg: AppConfig) -> bool:
    if study is None:
        return False
    programme = cfg.study.programme(study.programme_id)
    degree = cfg.study.degrees.get(study.degree)
    return (
        programme is not None
        and degree is not None
        and programme.degree == study.degree
        and 1 <= study.year <= degree.years
    )


def target_role_keys(status: str, is_teacher: bool, study: StudySel | None, cfg: AppConfig) -> set[str]:
    keys: set[str] = set()
    if status in STATUS_ROLE_KEYS:
        keys.add(STATUS_ROLE_KEYS[status])
    elif status == "unverified" and cfg.newcomer_role is not None:
        keys.add(cfg.newcomer_role)  # baseline role for members who aren't verified (e.g. after /forget-me)
    if is_teacher:
        keys.add("teacher")
    if status != "unverified" or is_teacher:
        keys.add("verified")
    if study is not None and status in cfg.study.allowed_statuses and valid_study(study, cfg):
        programme = cfg.study.programme(study.programme_id)
        assert programme is not None
        keys |= {programme_key(programme.role_id), year_key(study.degree, study.year)}
        if cfg.study.role_names.degree is not None:
            keys.add(degree_key(study.degree))
    return keys


def plan_changes(current: set[str], target: set[str], managed: set[str]) -> tuple[set[str], set[str]]:
    """Return (keys to add, keys to remove). Unmanaged roles are never touched."""
    return target - current, (current & managed) - target
