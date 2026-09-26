"""Member events, role reconciliation and periodic jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from stuard.timeutil import now_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

log = logging.getLogger(__name__)
DAY = 86_400


class EventsCog(commands.Cog):
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot
        self._reconciled = False

    async def cog_load(self) -> None:
        self.maintenance.start()
        self.reverify_job.start()

    async def cog_unload(self) -> None:
        self.maintenance.cancel()
        self.reverify_job.cancel()

    def _ours(self, guild: discord.Guild) -> bool:
        return guild.id == self.bot.settings.discord_guild_id

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        log.info("logged in as %s", self.bot.user)
        if self._reconciled:
            return
        self._reconciled = True
        if self.bot.guild is None:
            log.error("the bot is not a member of DISCORD_GUILD_ID=%s", self.bot.settings.discord_guild_id)
            return
        await self.reconcile()

    async def reconcile(self) -> None:
        """Re-apply the role plan to every known member (fixes drift after downtime)."""
        guild = self.bot.guild
        if guild is None:
            return
        changed = 0
        for row in await self.bot.repo.all_members():
            member = guild.get_member(row.user_id)
            if member is None:
                continue
            try:
                if await self.bot.roles.sync(member, reason="STUard: kontrola rolí"):
                    changed += 1
                    await asyncio.sleep(1)
            except discord.HTTPException:
                log.warning("could not reconcile roles of %s", row.user_id)
        log.info("role reconciliation finished, %d members updated", changed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not self._ours(member.guild) or await self.bot.repo.get_member(member.id) is None:
            return
        await self.bot.repo.set_left_at(member.id, None)
        await self.bot.roles.sync_user(member.id, reason="STUard: návrat na server")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if self._ours(member.guild) and await self.bot.repo.get_member(member.id) is not None:
            await self.bot.repo.set_left_at(member.id, now_ts())

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Keep the invariant "study roles only with Študent" when moderators edit roles by hand."""
        if not self._ours(after.guild):
            return
        role_id = (await self.bot.roles.role_map()).get("student")
        if role_id is None:
            return
        had, has = before.get_role(role_id) is not None, after.get_role(role_id) is not None
        if had == has:
            return
        row = await self.bot.repo.get_member(after.id)
        db_student = row is not None and row.status == "student"
        if has == db_student:
            return  # the bot's own change
        if had and not has:
            await self.bot.members.set_status(
                after.id, "former_student", method="mod", reason="rola Študent odobratá ručne"
            )
        else:
            await self.bot.audit.log(
                "student_role_added_manually",
                target_id=after.id,
                detail={"hint": "rola Študent sa prideľuje overením alebo cez /mod status"},
            )
            await self.bot.roles.sync_user(after.id, reason="STUard: rola Študent iba cez overenie")

    @tasks.loop(hours=1)
    async def maintenance(self) -> None:
        bot = self.bot
        try:
            now = now_ts()
            retention = bot.cfg.retention
            await bot.repo.purge_flows(now - retention.flows_hours * 3600)
            await bot.repo.purge_email_codes(now - retention.flows_hours * 3600)
            await bot.repo.purge_assertions(now)
            await bot.repo.purge_tombstones(now)
            await bot.repo.purge_audit(now - retention.audit_days * DAY)
            await bot.repo.purge_decided_reviews(now - retention.audit_days * DAY)
            await bot.reviews.expire_pending()
            for user_id in await bot.repo.left_members_before(now - retention.left_member_days * DAY):
                await bot.repo.delete_member(user_id)
                await bot.audit.log("left_member_purged", target_id=user_id, notify=False)
        except Exception:
            log.exception("maintenance job failed")

    @tasks.loop(hours=6)
    async def reverify_job(self) -> None:
        try:
            await self.bot.reverify.run()
        except Exception:
            log.exception("re-verification job failed")

    @maintenance.before_loop
    @reverify_job.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: StuardBot) -> None:
    await bot.add_cog(EventsCog(bot))
