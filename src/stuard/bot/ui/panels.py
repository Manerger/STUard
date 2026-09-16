"""Persistent panel messages (verification and study selection) and the shared /verify prompt."""

from __future__ import annotations

import math
from typing import Any

import discord

from stuard import texts as T
from stuard.bot.ui.study_select import open_study_editor
from stuard.services.verification import LINK_TTL_SECONDS


async def send_verify_prompt(interaction: discord.Interaction) -> None:
    bot: Any = interaction.client
    if interaction.guild is None:
        await interaction.response.send_message(T.NOT_IN_GUILD, ephemeral=True)
        return
    verification = bot.verification
    sso, microsoft, manual = (
        verification.sso_enabled(),
        verification.microsoft_enabled(),
        verification.manual_available(),
    )
    if not (sso or microsoft):
        await interaction.response.send_message(T.VERIFY_USE_MANUAL if manual else T.VERIFY_DISABLED, ephemeral=True)
        return

    key = str(interaction.user.id)
    if not bot.verify_limiter.hit(key):
        minutes = max(1, math.ceil(bot.verify_limiter.retry_after(key) / 60))
        await interaction.response.send_message(T.VERIFY_RATE_LIMITED.format(minutes=minutes), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    # One single-use link; whichever button is used first consumes it.
    url = await verification.create_link(interaction.user.id)
    view = discord.ui.View()
    lines = [T.VERIFY_INTRO]
    if sso:
        view.add_item(discord.ui.Button(label=T.VERIFY_LINK_BUTTON, url=url, style=discord.ButtonStyle.link))
        lines.append(T.VERIFY_OPTION_STU)
    if microsoft:
        view.add_item(
            discord.ui.Button(label=T.VERIFY_MICROSOFT_BUTTON, url=f"{url}&m=microsoft", style=discord.ButtonStyle.link)
        )
        lines.append(T.VERIFY_OPTION_MICROSOFT)
    if manual:
        lines.append(T.VERIFY_OPTION_MANUAL)
    lines.append(T.VERIFY_LINK_FOOTER.format(minutes=LINK_TTL_SECONDS // 60))
    await interaction.followup.send("\n".join(lines), view=view, ephemeral=True)


def verify_panel_embed() -> discord.Embed:
    return discord.Embed(title=T.VERIFY_PANEL_TITLE, description=T.VERIFY_PANEL_TEXT, colour=discord.Colour.blurple())


def study_panel_embed() -> discord.Embed:
    return discord.Embed(title=T.STUDY_PANEL_TITLE, description=T.STUDY_PANEL_TEXT, colour=discord.Colour.green())


class VerifyPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label=T.VERIFY_PANEL_BUTTON, style=discord.ButtonStyle.primary, custom_id="stuard:panel:verify")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await send_verify_prompt(interaction)

    @discord.ui.button(
        label=T.MANUAL_PANEL_BUTTON, style=discord.ButtonStyle.secondary, custom_id="stuard:panel:manual"
    )
    async def manual(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        client: Any = interaction.client
        text = T.MANUAL_INSTRUCTIONS if client.verification.manual_available() else T.MANUAL_DISABLED
        await interaction.response.send_message(text, ephemeral=True)


class StudyPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label=T.STUDY_PANEL_BUTTON, style=discord.ButtonStyle.primary, custom_id="stuard:panel:study")
    async def study(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await open_study_editor(interaction)
