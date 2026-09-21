from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from stuard import texts as T
from stuard.bot.checks import admin_only, moderator_only
from stuard.bot.ui.embeds import member_embed
from stuard.config import STATUSES
from stuard.security.tokens import subject_hmac
from stuard.timeutil import now_ts, to_dt

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

DAY = 86_400
STATUS_CHOICES = [app_commands.Choice(name=T.LABELS[s], value=s) for s in STATUSES]


@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
class ModerationCog(commands.GroupCog, group_name="mod", group_description="Moderátorské nástroje STUard"):
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="status", description="Nastaviť stav člena (napr. Bývalý študent, Absolvent)")
    @app_commands.describe(member="Člen", status="Nový stav", reason="Dôvod (zapíše sa do auditu)")
    @app_commands.choices(status=STATUS_CHOICES)
    @moderator_only()
    async def set_status(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        status: app_commands.Choice[str],
        reason: app_commands.Range[str, 3, 300],
    ) -> None:
        if member.bot:
            await interaction.response.send_message(T.MOD_TARGET_BOT, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.members.set_status(
            member.id, status.value, method="mod", actor_id=interaction.user.id, reason=reason
        )
        await interaction.followup.send(
            T.MOD_STATUS_DONE.format(member=member.mention, status=T.LABELS[status.value]), ephemeral=True
        )

    @app_commands.command(name="teacher", description="Pridať alebo odobrať rolu Vyučujúci")
    @app_commands.describe(member="Člen", action="Pridať alebo odobrať", reason="Dôvod (zapíše sa do auditu)")
    @app_commands.choices(
        action=[app_commands.Choice(name="pridať", value="add"), app_commands.Choice(name="odobrať", value="remove")]
    )
    @moderator_only()
    async def teacher(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        action: app_commands.Choice[str],
        reason: app_commands.Range[str, 3, 300],
    ) -> None:
        if member.bot:
            await interaction.response.send_message(T.MOD_TARGET_BOT, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        add = action.value == "add"
        await self.bot.members.set_teacher(member.id, add, actor_id=interaction.user.id, reason=reason)
        text = T.MOD_TEACHER_ADDED if add else T.MOD_TEACHER_REMOVED
        await interaction.followup.send(text.format(member=member.mention), ephemeral=True)

    @app_commands.command(name="info", description="Stav overenia člena")
    @app_commands.describe(member="Člen")
    @moderator_only()
    async def info(self, interaction: discord.Interaction, member: discord.Member) -> None:
        repo = self.bot.repo
        row = await repo.get_member(member.id)
        pending = [r for r in await repo.reviews_for_user(member.id) if r.status == "pending"]
        embed = member_embed(
            self.bot.cfg,
            T.MOD_INFO_TITLE.format(name=member.display_name),
            row,
            await repo.get_study(member.id),
            await repo.get_identity_by_user(member.id),
            pending=pending,
            show_affiliations=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="unlink", description="Odpojiť UIS účet od člena (napr. ak ho treba prepojiť inde)")
    @app_commands.describe(member="Člen")
    @moderator_only()
    async def unlink(self, interaction: discord.Interaction, member: discord.Member) -> None:
        if await self.bot.repo.unbind_user(member.id):
            await self.bot.audit.log("identity_unlinked", actor_id=interaction.user.id, target_id=member.id)
            await interaction.response.send_message(T.MOD_UNLINKED.format(member=member.mention), ephemeral=True)
        else:
            await interaction.response.send_message(T.MOD_NOT_LINKED.format(member=member.mention), ephemeral=True)

    @app_commands.command(
        name="readmit", description="Zrušiť dočasnú blokáciu (po /forget-me), aby sa člen mohol znova overiť"
    )
    @app_commands.describe(member="Člen")
    @moderator_only()
    async def readmit(self, interaction: discord.Interaction, member: discord.Member) -> None:
        cleared = await self.bot.repo.clear_tombstones_for_user(member.id)
        if cleared:
            await self.bot.audit.log(
                "tombstone_cleared", actor_id=interaction.user.id, target_id=member.id, detail={"count": cleared}
            )
            await interaction.response.send_message(T.MOD_READMIT_DONE.format(member=member.mention), ephemeral=True)
        else:
            await interaction.response.send_message(T.MOD_READMIT_NONE.format(member=member.mention), ephemeral=True)

    @app_commands.command(name="reverify", description="Vyžiadať od člena obnovenie overenia")
    @app_commands.describe(member="Člen", days="Počet dní na obnovenie")
    @moderator_only()
    async def reverify(
        self, interaction: discord.Interaction, member: discord.Member, days: app_commands.Range[int, 1, 60] = 7
    ) -> None:
        bot = self.bot
        row = await bot.repo.get_member(member.id)
        if row is None or row.status == "unverified":
            await interaction.response.send_message(T.MOD_NOT_VERIFIED.format(member=member.mention), ephemeral=True)
            return
        now = now_ts()
        deadline = now + days * DAY
        await bot.repo.set_member_status(
            member.id, status=row.status, method=None, now=now, valid_until=deadline, mark_verified=False
        )
        await bot.audit.log(
            "reverify_requested", actor_id=interaction.user.id, target_id=member.id, detail={"days": days}
        )
        deadline_text = to_dt(deadline).astimezone(bot.cfg.tz).strftime("%d.%m.%Y")
        guild_name = interaction.guild.name if interaction.guild else "server"
        await bot.dm(member.id, T.MOD_REVERIFY_DM.format(guild=guild_name, deadline=deadline_text))
        await interaction.response.send_message(
            T.MOD_REVERIFY_DONE.format(member=member.mention, deadline=deadline_text), ephemeral=True
        )

    @app_commands.command(name="requests", description="Čakajúce žiadosti o overenie")
    @moderator_only()
    async def requests(self, interaction: discord.Interaction) -> None:
        pending = await self.bot.repo.pending_reviews(25)
        if not pending:
            await interaction.response.send_message(T.MOD_REQUESTS_EMPTY, ephemeral=True)
            return
        guild_id = interaction.guild_id
        lines = []
        for review in pending:
            link = (
                f" · [otvoriť](https://discord.com/channels/{guild_id}/{review.channel_id}/{review.message_id})"
                if review.channel_id and review.message_id
                else ""
            )
            created = discord.utils.format_dt(to_dt(review.created_at), "R")
            lines.append(f"#{review.id} · <@{review.user_id}> · {T.REVIEW_TITLES[review.source]} · {created}{link}")
        embed = discord.Embed(title=T.MOD_REQUESTS_TITLE, description="\n".join(lines)[:4000])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="lookup", description="Nájsť člena podľa čísla AIS ID (iba admin, zapisuje sa do auditu)"
    )
    @app_commands.describe(ais_id="Číslo AIS ID, napr. 123456 (pri kontách bez AIS ID celý školský login)")
    @admin_only()
    async def lookup(self, interaction: discord.Interaction, ais_id: app_commands.Range[str, 2, 100]) -> None:
        bot = self.bot
        value = ais_id.strip()
        # Accounts are identified as "<AIS ID>@stuba.sk" (Microsoft employeeId, STU eduPersonPrincipalName).
        subject = value if "@" in value else f"{value}@{bot.cfg.microsoft.allowed_domains[0]}"
        identity = await bot.repo.get_identity_by_subject(subject_hmac(bot.settings.hmac_key, subject))
        await bot.audit.log(
            "identity_lookup", actor_id=interaction.user.id, target_id=identity.user_id if identity else None
        )
        if identity is None:
            await interaction.response.send_message(T.MOD_LOOKUP_NONE, ephemeral=True)
        else:
            await interaction.response.send_message(
                T.MOD_LOOKUP_FOUND.format(member=f"<@{identity.user_id}>"), ephemeral=True
            )


async def setup(bot: StuardBot) -> None:
    await bot.add_cog(ModerationCog(bot))
