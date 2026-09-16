"""Linking the server's existing roles (1-BC, 2-ing, …) instead of creating duplicates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from stuard.config import AppConfig
from stuard.db.repos import Repo
from stuard.services.roles import RoleService
from tests.fakes import FakeBot


class FakeRole:
    def __init__(self, role_id: int, name: str, position: int, *, managed: bool = False, default: bool = False):
        self.id = role_id
        self.name = name
        self.position = position
        self.managed = managed
        self.default = default
        self.members: list[Any] = []

    def is_default(self) -> bool:
        return self.default

    def __ge__(self, other: FakeRole) -> bool:
        return self.position >= other.position


class FakeGuild:
    def __init__(self, roles: list[FakeRole], bot_role: FakeRole) -> None:
        self.roles = roles
        self.me = SimpleNamespace(top_role=bot_role)
        self.created: list[str] = []

    def get_role(self, role_id: int) -> FakeRole | None:
        return next((r for r in self.roles if r.id == role_id), None)

    async def create_role(self, *, name: str, **kwargs: Any) -> FakeRole:
        role = FakeRole(1000 + len(self.created), name, position=1)
        self.roles.append(role)
        self.created.append(name)
        return role


def existing_server() -> FakeGuild:
    bot_role = FakeRole(99, "STUard", 50, managed=True)
    roles = [
        FakeRole(0, "@everyone", 0, default=True),
        FakeRole(1, "1-BC", 10),
        FakeRole(2, "2-BC", 11),
        FakeRole(3, "3-bc", 12),  # different case is still recognised
        FakeRole(4, "1-ing", 13),
        FakeRole(5, "2-ing", 14),
        FakeRole(6, "Server admin", 60),
        bot_role,
    ]
    return FakeGuild(roles, bot_role)


def service_for(repo: Repo, cfg: AppConfig, guild: FakeGuild) -> RoleService:
    bot = FakeBot(repo, cfg)
    bot.guild = guild  # type: ignore[assignment]
    return RoleService(bot)  # type: ignore[arg-type]


async def test_existing_year_roles_are_linked_not_duplicated(repo: Repo, cfg: AppConfig) -> None:
    guild = existing_server()
    service = service_for(repo, cfg, guild)

    preview = await service.ensure_roles(create=False, adopt=False)
    assert sorted(preview.adoptable) == ["1-BC", "1-ing", "2-BC", "2-ing", "3-bc"]
    assert await repo.role_map() == {}  # a check never changes anything

    report = await service.ensure_roles(create=True, adopt=True)
    role_map = await repo.role_map()
    assert [role_map[f"year:bc:{y}"] for y in (1, 2, 3)] == [1, 2, 3]
    assert [role_map[f"year:ing:{y}"] for y in (1, 2)] == [4, 5]
    assert not {"1-BC", "2-BC", "3-BC", "1-ing", "2-ing", "Server admin"} & set(guild.created)
    assert {"Študent", "Overený", "1-PhD", "Bc. Mechatronika"} <= set(guild.created)
    assert report.too_high == []

    again = await service.ensure_roles(create=False, adopt=False)
    assert again.healthy and not again.created


async def test_existing_role_above_the_bot_is_reported(repo: Repo, cfg: AppConfig) -> None:
    guild = existing_server()
    role = guild.get_role(1)
    assert role is not None
    role.position = 70  # 1-BC dragged above the bot's role
    report = await service_for(repo, cfg, guild).ensure_roles(create=False, adopt=False)
    assert report.too_high == ["1-BC"]


async def test_counts_unverified_holders_of_study_roles(repo: Repo, cfg: AppConfig) -> None:
    guild = existing_server()
    first_bc, admin = guild.get_role(1), guild.get_role(6)
    assert first_bc is not None and admin is not None
    first_bc.members = [SimpleNamespace(id=10), SimpleNamespace(id=11)]
    admin.members = [SimpleNamespace(id=12)]  # not a study role
    await repo.set_member_status(11, status="student", method="sso", now=1, valid_until=None)
    service = service_for(repo, cfg, guild)
    report = await service.ensure_roles(create=False, adopt=False)
    assert await service.unverified_study_role_holders(report.roles) == 1
