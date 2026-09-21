from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from stuard import texts as T
from stuard.bot.ui.panels import send_verify_prompt

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

ROLE_CHOICES = [
    app_commands.Choice(name=T.LABELS["student"], value="student"),
    app_commands.Choice(name=T.LABELS["applicant"], value="applicant"),
    app_commands.Choice(name=T.LABELS["teacher"], value="teacher"),
    app_commands.Choice(name=T.LABELS["alumni"], value="alumni"),
]


class VerifyCog(commands.Cog):
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    @app_commands.command(name="verify", description="Overenie cez UIS STU (heslo zadávaš iba na idp.stuba.sk)")
    @app_commands.guild_only()
    async def verify(self, interaction: discord.Interaction) -> None:
        await send_verify_prompt(interaction)

    @app_commands.command(name="verify-manual", description="Manuálne overenie moderátorom podľa snímky z UIS")
    @app_commands.guild_only()
    @app_commands.describe(
        rola="Rola, o ktorú žiadaš",
        screenshot="Snímka obrazovky z UIS (začierni rodné číslo a dátum narodenia)",
        poznamka="Voliteľná poznámka pre moderátorov",
    )
    @app_commands.choices(rola=ROLE_CHOICES)
    async def verify_manual(
        self,
        interaction: discord.Interaction,
        rola: app_commands.Choice[str],
        screenshot: discord.Attachment,
        poznamka: app_commands.Range[str, 1, 500] | None = None,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(T.NOT_IN_GUILD, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        message = await self.bot.reviews.submit_manual(interaction.user, rola.value, screenshot, poznamka)
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(name="verify-email", description="Overenie kódom na školský e-mail (@stuba.sk)")
    @app_commands.guild_only()
    @app_commands.describe(login="Tvoj školský login (napr. xnovak) alebo číslo AIS ID")
    async def verify_email(self, interaction: discord.Interaction, login: app_commands.Range[str, 2, 64]) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(T.NOT_IN_GUILD, ephemeral=True)
            return
        if not self.bot.email.enabled():
            await interaction.response.send_message(T.EMAIL_DISABLED, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        message = await self.bot.email.request_code(interaction.user, login)
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(name="verify-code", description="Zadať overovací kód z e-mailu")
    @app_commands.guild_only()
    @app_commands.describe(code="Kód z e-mailu")
    async def verify_code(self, interaction: discord.Interaction, code: app_commands.Range[str, 4, 16]) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(T.NOT_IN_GUILD, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        message = await self.bot.email.submit_code(interaction.user, code)
        await interaction.followup.send(message, ephemeral=True)

async def setup(bot: StuardBot) -> None:
    await bot.add_cog(VerifyCog(bot))
