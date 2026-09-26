from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from stuard import texts as T

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot


class ForgetConfirmView(discord.ui.View):
    def __init__(self, bot: StuardBot, user_id: int) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label=T.FORGET_BUTTON, style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await interaction.response.defer()
        await self.bot.privacy.forget(self.user_id)
        await interaction.edit_original_response(content=T.FORGET_DONE, view=None)
        self.stop()

    @discord.ui.button(label=T.CANCEL, style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await interaction.response.edit_message(content=T.CANCELLED, view=None)
        self.stop()


class PrivacyCog(commands.Cog):
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    @app_commands.command(name="privacy", description="Ochrana osobných údajov a kópia údajov, ktoré o tebe bot má")
    async def privacy(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        data = await self.bot.privacy.export(interaction.user.id)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        embed = discord.Embed(title=T.PRIVACY_TITLE, description="\n\n".join(T.privacy_notice(self.bot.cfg))[:4000])
        await interaction.followup.send(
            T.PRIVACY_EXPORT_NOTE,
            embed=embed,
            file=discord.File(io.BytesIO(payload), filename="stuard-moje-udaje.json"),
            ephemeral=True,
        )

    @app_commands.command(name="forget-me", description="Vymazať všetky tvoje údaje z bota (stratíš overené roly)")
    @app_commands.guild_only()
    async def forget_me(self, interaction: discord.Interaction) -> None:
        days = self.bot.cfg.retention.tombstone_days
        extra = T.FORGET_TOMBSTONE.format(duration=T.days_sk(days)) if days > 0 else ""
        await interaction.response.send_message(
            T.FORGET_CONFIRM.format(extra=extra), view=ForgetConfirmView(self.bot, interaction.user.id), ephemeral=True
        )


async def setup(bot: StuardBot) -> None:
    await bot.add_cog(PrivacyCog(bot))
