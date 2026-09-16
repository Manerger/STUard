from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from stuard import texts as T
from stuard.bot.ui.embeds import member_embed
from stuard.bot.ui.study_select import StudyEditorView

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot


class ProfileCog(commands.Cog):
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    @app_commands.command(name="profile", description="Tvoj stav overenia, študijný program a ročník")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction) -> None:
        bot = self.bot
        user_id = interaction.user.id
        member = await bot.repo.get_member(user_id)
        if member is None or (member.status == "unverified" and not member.is_teacher):
            await interaction.response.send_message(T.PROFILE_UNVERIFIED, ephemeral=True)
            return
        study = await bot.repo.get_study(user_id)
        identity = await bot.repo.get_identity_by_user(user_id)
        kwargs: dict[str, Any] = {"embed": member_embed(bot.cfg, T.PROFILE_TITLE, member, study, identity)}
        if member.status in bot.cfg.study.allowed_statuses:
            kwargs["view"] = StudyEditorView(bot, user_id, study)
        await interaction.response.send_message(ephemeral=True, **kwargs)


async def setup(bot: StuardBot) -> None:
    await bot.add_cog(ProfileCog(bot))
