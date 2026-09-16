"""Apply the computed role plan to Discord members and manage the bot's roles."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord

from stuard.domain.roleplan import is_study_key, plan_changes, role_specs, target_role_keys

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

log = logging.getLogger(__name__)


def _fold(name: str) -> str:
    return name.strip().casefold()


@dataclass
class RoleReport:
    ok: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    adoptable: list[str] = field(default_factory=list)  # existing roles /setup roles would link
    created: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    too_high: list[str] = field(default_factory=list)
    roles: dict[str, discord.Role] = field(default_factory=dict)  # key → existing Discord role

    @property
    def healthy(self) -> bool:
        return not self.missing and not self.adoptable and not self.too_high


class RoleService:
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot
        self._map: dict[str, int] | None = None

    def invalidate(self) -> None:
        self._map = None

    async def role_map(self) -> dict[str, int]:
        if self._map is None:
            self._map = await self.bot.repo.role_map()
        return self._map

    async def role_for(self, key: str) -> discord.Role | None:
        guild = self.bot.guild
        role_id = (await self.role_map()).get(key)
        return guild.get_role(role_id) if guild and role_id else None

    async def target_keys(self, user_id: int) -> set[str]:
        member = await self.bot.repo.get_member(user_id)
        if member is None:
            return set()
        study = await self.bot.repo.get_study(user_id)
        return target_role_keys(member.status, member.is_teacher, study, self.bot.cfg)

    async def sync(self, member: discord.Member, *, reason: str) -> bool:
        """Make the member's managed roles match the database in a single API call."""
        guild = member.guild
        specs = role_specs(self.bot.cfg)
        rmap = await self.role_map()
        key_by_id = {role_id: key for key, role_id in rmap.items() if key in specs}
        current = {key_by_id[r.id] for r in member.roles if r.id in key_by_id}
        add, remove = plan_changes(current, await self.target_keys(member.id), set(specs))

        to_add: list[discord.Role] = []
        for key in sorted(add):
            role = guild.get_role(rmap.get(key, 0))
            if role is None:
                log.warning("role %s is not set up; run /setup roles", key)
                continue
            to_add.append(role)
        if not to_add and not remove:
            return False
        new_roles = [r for r in member.roles if not r.is_default() and key_by_id.get(r.id) not in remove]
        new_roles.extend(to_add)
        await member.edit(roles=new_roles, reason=reason[:500])
        return True

    async def sync_user(self, user_id: int, *, reason: str) -> bool:
        guild = self.bot.guild
        if guild is None:
            return False
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                return False
        try:
            return await self.sync(member, reason=reason)
        except discord.Forbidden:
            log.error("missing permission to edit roles of %s — is the bot role above the managed roles?", user_id)
        except discord.HTTPException:
            log.exception("failed to sync roles of %s", user_id)
        return False

    async def ensure_roles(self, *, create: bool, adopt: bool) -> RoleReport:
        """Link every managed role to a Discord role.

        Roles that already exist on the server with the same name (ignoring case, e.g. a hand-made "1-BC")
        are linked instead of duplicated. With adopt=False they are only reported.
        """
        guild = self.bot.guild
        if guild is None:
            raise RuntimeError("guild is not available")
        report = RoleReport()
        rmap = await self.bot.repo.role_map()
        linked = {role_id for role_id in rmap.values() if guild.get_role(role_id) is not None}
        exact: dict[str, discord.Role] = {}
        folded: dict[str, discord.Role] = {}
        for role in guild.roles:
            if role.managed or role.is_default() or role.id in linked:
                continue
            exact.setdefault(role.name, role)
            folded.setdefault(_fold(role.name), role)
        top = guild.me.top_role

        for key, spec in role_specs(self.bot.cfg).items():
            role = guild.get_role(rmap[key]) if key in rmap else None
            if role is not None:
                report.ok.append(spec.name)
            elif (existing := exact.get(spec.name) or folded.get(_fold(spec.name))) is not None:
                role = existing
                exact.pop(role.name, None)
                folded.pop(_fold(role.name), None)
                if adopt:
                    await self.bot.repo.set_role_mapping(key, role.id)
                    report.adopted.append(role.name)
                else:
                    report.adoptable.append(role.name)
            elif create:
                role = await guild.create_role(
                    name=spec.name,
                    colour=discord.Colour(spec.color or 0),
                    hoist=spec.hoist,
                    mentionable=False,
                    permissions=discord.Permissions.none(),
                    reason="STUard /setup roles",
                )
                await self.bot.repo.set_role_mapping(key, role.id)
                report.created.append(spec.name)
            else:
                report.missing.append(spec.name)
                continue
            report.roles[key] = role
            if role >= top:
                report.too_high.append(role.name)
        self.invalidate()
        return report

    async def unverified_study_role_holders(self, roles: dict[str, discord.Role]) -> int:
        """Members holding a study role (e.g. a hand-assigned "1-BC") who are not verified students."""
        holders = {member.id for key, role in roles.items() if is_study_key(key) for member in role.members}
        count = 0
        for user_id in holders:
            row = await self.bot.repo.get_member(user_id)
            if row is None or row.status not in self.bot.cfg.study.allowed_statuses:
                count += 1
        return count
