"""Non-secret configuration loaded from config.yaml."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Status = Literal["unverified", "applicant", "student", "former_student", "alumni"]
STATUSES: tuple[str, ...] = ("unverified", "applicant", "student", "former_student", "alumni")
IDENTITY_ROLE_KEYS: tuple[str, ...] = ("verified", "student", "applicant", "teacher", "alumni", "former_student")
# Status → identity role key ("unverified" has no role).
STATUS_ROLE_KEYS: dict[str, str] = {
    "student": "student",
    "applicant": "applicant",
    "alumni": "alumni",
    "former_student": "former_student",
}
DISCORD_SELECT_LIMIT = 25
DISCORD_NAME_LIMIT = 100
STU_TENANT_ID = "25733538-6b16-4aa3-8ed6-297eb79b8e06"

_MMDD = re.compile(r"^\d{2}-\d{2}$")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


def parse_mmdd(value: str) -> tuple[int, int]:
    if not _MMDD.match(value):
        raise ValueError(f"expected MM-DD, got {value!r}")
    month, day = int(value[:2]), int(value[3:])
    date(2001, month, day)  # 2001 is not a leap year, so 02-29 is rejected too
    return month, day


def duplicate_names(names: Iterable[str]) -> list[str]:
    """Names colliding with an earlier one, ignoring case and surrounding spaces (as role adoption does)."""
    seen: set[str] = set()
    duplicates = []
    for name in names:
        folded = name.strip().casefold()
        if folded in seen:
            duplicates.append(name)
        seen.add(folded)
    return duplicates


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoleDef(_Model):
    name: str = Field(min_length=1, max_length=DISCORD_NAME_LIMIT)
    color: str | None = None
    hoist: bool = False

    @field_validator("color")
    @classmethod
    def _color(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("color must look like #1f77b4")
        return value

    @property
    def color_int(self) -> int | None:
        return int(self.color[1:], 16) if self.color else None


ChannelRef = int | str


class ChannelsCfg(_Model):
    """Each channel is a channel ID or a channel name (e.g. admin_room_verifikacie)."""

    mod_review: ChannelRef | None = None
    audit: ChannelRef | None = None
    verify: ChannelRef | None = None
    study_panel: ChannelRef | None = None

    @field_validator("*")
    @classmethod
    def _clean(cls, value: ChannelRef | None) -> ChannelRef | None:
        if isinstance(value, str):
            value = value.strip().lstrip("#").strip()
            if not value:
                raise ValueError("channel name must not be empty")
            if value.isdigit():
                return int(value)
        return value


class StatusRule(_Model):
    any_of: list[str] = Field(min_length=1)
    status: Status | None = None
    action: Literal["assign", "manual_review"] = "assign"
    suggest: Status | None = None

    @model_validator(mode="after")
    def _check(self) -> StatusRule:
        if self.action == "assign" and self.status is None:
            raise ValueError("status_rules: 'status' is required when action is 'assign'")
        return self


def _default_status_rules() -> list[StatusRule]:
    return [
        StatusRule(any_of=["student"], status="student"),
        StatusRule(any_of=["alum"], status="alumni"),
        StatusRule(any_of=["affiliate"], action="manual_review", suggest="applicant"),
    ]


class SsoCfg(_Model):
    enabled: bool = False
    allowed_scopes: list[str] = Field(default_factory=lambda: ["stuba.sk"], min_length=1)
    identity_attribute: Literal["eppn", "pairwise_id", "persistent_nameid"] = "eppn"
    force_authn: bool = True
    # Entity categories published in the SP metadata (the federation decides which to grant),
    # e.g. https://refeds.org/category/pseudonymous or https://refeds.org/category/code-of-conduct/v2.
    entity_categories: list[str] = Field(default_factory=list, max_length=10)
    display_name: str = "STUard – overenie MTF STU"
    description: str = "Overenie členov Discord servera študentov MTF STU."
    status_rules: list[StatusRule] = Field(default_factory=_default_status_rules)
    teacher_affiliations: list[str] = Field(default_factory=lambda: ["faculty", "staff", "employee"])
    unmatched: Literal["manual_review", "reject"] = "manual_review"
    log_unmapped_values: bool = True

    @field_validator("entity_categories")
    @classmethod
    def _categories(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.startswith(("http://", "https://")):
                raise ValueError(f"sso.entity_categories: {value!r} is not a category URI")
        return values


class MicrosoftCfg(_Model):
    enabled: bool = False
    tenant_id: str = STU_TENANT_ID
    allowed_domains: list[str] = Field(default_factory=lambda: ["stuba.sk"], min_length=1)
    # Account type (employeeType) read from Microsoft Graph after sign-in.
    student_types: list[str] = Field(default_factory=lambda: ["student"])
    teacher_types: list[str] = Field(default_factory=lambda: ["employee", "staff", "faculty"])  # never automatic
    unmatched: Literal["manual_review", "student"] = "manual_review"
    show_login_to_moderators: bool = True

    @field_validator("tenant_id")
    @classmethod
    def _tenant(cls, value: str) -> str:
        if not _GUID.match(value):
            raise ValueError("microsoft.tenant_id must be a tenant GUID")
        return value.lower()


class ManualCfg(_Model):
    mode: Literal["when_sso_disabled", "always", "off"] = "when_sso_disabled"
    max_bytes: int = Field(default=8_000_000, gt=0, le=25_000_000)
    reject_cooldown_hours: int = Field(default=24, ge=0)
    expire_days: int = Field(default=7, ge=1)


class LdapCfg(_Model):
    """Optional enrichment: look a login up in STU's directory to get faculty and student/staff type.

    Anonymous bind over LDAPS; reachable only inside STU's network (run the bot behind the STU VPN).
    """

    enabled: bool = False
    url: str = "ldaps://ldap.stuba.sk:636"
    base_dn: str = "ou=People,dc=stuba,dc=sk"
    login_attribute: str = "uid"
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class EmailCfg(_Model):
    """Email-code verification: a one-time code sent to <login>@stuba.sk proves the person owns a real STU mailbox.

    Needs SMTP settings in .env. LDAP enrichment (optional) adds faculty + student/staff type and the AIS ID
    (so identity matches the Microsoft/SAML fingerprint); without it, a verified mailbox defaults to Študent.
    """

    enabled: bool = False
    allowed_domains: list[str] = Field(default_factory=lambda: ["stuba.sk"], min_length=1)
    code_ttl_minutes: int = Field(default=15, ge=1, le=120)
    max_attempts: int = Field(default=5, ge=1, le=20)
    ldap: LdapCfg = Field(default_factory=LdapCfg)
    allowed_faculties: list[str] = Field(default_factory=lambda: ["MTF"])  # empty = any faculty
    student_types: list[str] = Field(default_factory=lambda: ["student"])
    teacher_types: list[str] = Field(default_factory=lambda: ["employee", "staff", "faculty", "researcher"])
    unmatched: Literal["manual_review", "student"] = "manual_review"  # LDAP present, type not recognized
    without_ldap: Literal["student", "manual_review"] = "student"  # no LDAP enrichment available

    @field_validator("allowed_faculties")
    @classmethod
    def _upper(cls, values: list[str]) -> list[str]:
        return [v.strip().upper() for v in values]


class ReverifyCfg(_Model):
    enabled: bool = True
    applies_to: list[Status] = Field(default_factory=lambda: ["student", "applicant"])
    window_start: str = "09-20"
    deadline: str = "10-31"
    reminders_days_before: list[int] = Field(default_factory=lambda: [30, 14, 3])
    on_expired: dict[Status, Status] = Field(
        default_factory=lambda: {"student": "former_student", "applicant": "unverified"}
    )

    @model_validator(mode="after")
    def _check(self) -> ReverifyCfg:
        if parse_mmdd(self.window_start) >= parse_mmdd(self.deadline):
            raise ValueError("reverify.window_start must be before reverify.deadline in the same calendar year")
        if any(d <= 0 for d in self.reminders_days_before):
            raise ValueError("reverify.reminders_days_before must contain positive numbers")
        return self


class RetentionCfg(_Model):
    flows_hours: int = Field(default=24, ge=1)
    left_member_days: int = Field(default=30, ge=0)
    audit_days: int = Field(default=180, ge=1)
    tombstone_days: int = Field(default=30, ge=0)


class Degree(_Model):
    label: str = Field(min_length=1, max_length=20)
    years: int = Field(ge=1, le=10)
    # Name of this degree's year roles, e.g. "{year}-BC". Defaults to study.role_names.year.
    year_role: str | None = None


class Programme(_Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    degree: str
    name: str = Field(min_length=1, max_length=DISCORD_NAME_LIMIT)
    lang: Literal["sk", "en"] = "sk"
    role_group: str | None = None

    @property
    def role_id(self) -> str:
        """Programmes sharing a role (e.g. SK/EN variants) point at the same role."""
        return self.role_group or self.id


class RoleNames(_Model):
    degree: str | None = "{degree}"  # null = no separate degree roles
    programme: str = "{degree} {programme}"
    year: str = "{degree} {year}. ročník"


class StudyCfg(_Model):
    allowed_statuses: list[Status] = Field(default_factory=lambda: ["student"])
    role_names: RoleNames = Field(default_factory=RoleNames)
    degrees: dict[str, Degree] = Field(min_length=1, max_length=DISCORD_SELECT_LIMIT)
    programmes: list[Programme] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> StudyCfg:
        by_id: dict[str, Programme] = {}
        for p in self.programmes:
            if p.id in by_id:
                raise ValueError(f"study.programmes: duplicate id {p.id!r}")
            if p.degree not in self.degrees:
                raise ValueError(f"study.programmes[{p.id}]: unknown degree {p.degree!r}")
            by_id[p.id] = p
        for p in self.programmes:
            if p.role_group is None:
                continue
            target = by_id.get(p.role_group)
            if target is None or target.role_group is not None or target.degree != p.degree:
                raise ValueError(
                    f"study.programmes[{p.id}]: role_group must name a programme of the same degree "
                    "that has no role_group itself"
                )
        for key in self.degrees:
            count = sum(1 for p in self.programmes if p.degree == key)
            if count > DISCORD_SELECT_LIMIT:
                raise ValueError(f"study: degree {key!r} has {count} programmes (Discord menus allow 25)")
        try:
            names = self.role_name_list()
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"study: invalid role name template ({exc!r})") from exc
        too_long = [n for n in names if len(n) > DISCORD_NAME_LIMIT]
        if too_long:
            raise ValueError(f"study: role name longer than 100 characters: {too_long[0]!r}")
        duplicates = duplicate_names(names)
        if duplicates:
            raise ValueError(f"study: duplicate role name {duplicates[0]!r} (does every year_role contain {{year}}?)")
        return self

    def programme(self, programme_id: str) -> Programme | None:
        return next((p for p in self.programmes if p.id == programme_id), None)

    def programmes_for(self, degree: str) -> list[Programme]:
        return [p for p in self.programmes if p.degree == degree]

    def degree_role_name(self, degree: str) -> str | None:
        template = self.role_names.degree
        return None if template is None else template.format(degree=self.degrees[degree].label)

    def year_role_name(self, degree: str, year: int) -> str:
        info = self.degrees[degree]
        return (info.year_role or self.role_names.year).format(degree=info.label, year=year)

    def programme_role_name(self, programme: Programme) -> str:
        return self.role_names.programme.format(degree=self.degrees[programme.degree].label, programme=programme.name)

    def role_name_list(self) -> list[str]:
        names: list[str] = []
        for key, info in self.degrees.items():
            degree_name = self.degree_role_name(key)
            if degree_name is not None:
                names.append(degree_name)
            names += [self.year_role_name(key, year) for year in range(1, info.years + 1)]
        names += [self.programme_role_name(p) for p in self.programmes if p.role_group is None]
        return names


class AppConfig(_Model):
    timezone: str = "Europe/Bratislava"
    privacy_contact: str = ""
    moderator_role_ids: list[int] = Field(default_factory=list)
    admin_role_ids: list[int] = Field(default_factory=list)
    channels: ChannelsCfg = Field(default_factory=ChannelsCfg)
    roles: dict[str, RoleDef]
    sso: SsoCfg = Field(default_factory=SsoCfg)
    microsoft: MicrosoftCfg = Field(default_factory=MicrosoftCfg)
    manual: ManualCfg = Field(default_factory=ManualCfg)
    email: EmailCfg = Field(default_factory=EmailCfg)
    reverify: ReverifyCfg = Field(default_factory=ReverifyCfg)
    retention: RetentionCfg = Field(default_factory=RetentionCfg)
    study: StudyCfg

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _check_roles(self) -> AppConfig:
        missing = [k for k in IDENTITY_ROLE_KEYS if k not in self.roles]
        extra = [k for k in self.roles if k not in IDENTITY_ROLE_KEYS]
        if missing:
            raise ValueError(f"roles: missing keys {missing}")
        if extra:
            raise ValueError(f"roles: unknown keys {extra} (allowed: {list(IDENTITY_ROLE_KEYS)})")
        clashes = duplicate_names([r.name for r in self.roles.values()] + self.study.role_name_list())
        if clashes:
            raise ValueError(f"role names must be unique (case-insensitive): {clashes[0]!r}")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_config(path: Path) -> AppConfig:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return AppConfig.model_validate(data)
