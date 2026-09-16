from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import discord
import yaml
from discord import app_commands
from discord.ext import commands

from stuard import texts as T
from stuard.bot.checks import admin_only
from stuard.bot.ui.panels import StudyPanelView, VerifyPanelView, study_panel_embed, verify_panel_embed
from stuard.domain.lifecycle import deadline_for_year
from stuard.timeutil import now_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

CHANNEL_KEYS = ("mod_review", "audit", "verify", "study_panel")
REQUIRED_PERMISSIONS = (
    ("manage_roles", "Manage Roles"),
    ("view_channel", "View Channels"),
    ("send_messages", "Send Messages"),
    ("embed_links", "Embed Links"),
    ("attach_files", "Attach Files"),
)
OVERRIDE_CHOICES = [
    app_commands.Choice(name=T.STATE_ON, value="on"),
    app_commands.Choice(name=T.STATE_OFF, value="off"),
    app_commands.Choice(name=T.STATE_DEFAULT, value="default"),
]
OVERRIDE_VALUES: dict[str, bool | None] = {"on": True, "off": False, "default": None}


def _state(value: bool | None) -> str:
    return T.STATE_DEFAULT if value is None else _on_off(value)


def _on_off(value: bool) -> str:
    return T.STATE_ON if value else T.STATE_OFF


@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
class SetupCog(commands.GroupCog, group_name="setup", group_description="Nastavenie bota STUard (admin)"):
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="check", description="Skontrolovať roly, oprávnenia, kanály a spôsoby overenia")
    @admin_only()
    async def check(self, interaction: discord.Interaction) -> None:
        bot = self.bot
        guild = interaction.guild
        assert guild is not None
        await interaction.response.defer(ephemeral=True, thinking=True)
        report = await bot.roles.ensure_roles(create=False, adopt=False)
        lines = [T.SETUP_ROLES_OK.format(n=len(report.ok))]
        if report.adoptable:
            lines.append(T.SETUP_ROLES_ADOPTABLE.format(names=", ".join(report.adoptable)))
        if report.missing:
            lines.append(T.SETUP_ROLES_MISSING.format(names=", ".join(report.missing)))
        if report.too_high:
            lines.append(T.SETUP_ROLES_TOO_HIGH.format(names=", ".join(report.too_high)))
        unverified = await bot.roles.unverified_study_role_holders(report.roles)
        if unverified:
            lines.append(T.SETUP_UNVERIFIED_HOLDERS.format(n=unverified))
        permissions = guild.me.guild_permissions
        lines += [
            T.SETUP_PERM_MISSING.format(perm=label)
            for attr, label in REQUIRED_PERMISSIONS
            if not getattr(permissions, attr)
        ]
        for key in CHANNEL_KEYS:
            channel = bot.resolve_channel(getattr(bot.cfg.channels, key))
            if channel is None or not channel.permissions_for(guild.me).send_messages:
                lines.append(T.SETUP_CHANNEL_MISSING.format(name=key))
            else:
                lines.append(T.SETUP_CHANNEL_OK.format(name=key, channel=channel.mention))
        verification = bot.verification
        lines.append(
            T.SETUP_SSO_STATE.format(
                state=_on_off(verification.sso_enabled()),
                config=_on_off(bot.cfg.sso.enabled),
                override=_state(bot.sso_override),
                files="OK" if bot.saml else "chýbajú",
            )
        )
        lines.append(
            T.SETUP_MICROSOFT_STATE.format(
                state=_on_off(verification.microsoft_enabled()),
                config=_on_off(bot.cfg.microsoft.enabled),
                override=_state(bot.microsoft_override),
                app="OK" if bot.microsoft else "chýba",
            )
        )
        lines.append(T.SETUP_MANUAL_STATE.format(state=_on_off(verification.manual_available())))
        lines.append(f"SP metadáta: {bot.settings.public_base_url}/saml/metadata")
        embed = discord.Embed(title=T.SETUP_CHECK_TITLE, description="\n".join(lines)[:4000])
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="roles", description="Vytvoriť chýbajúce roly alebo prevziať existujúce s rovnakým názvom"
    )
    @admin_only()
    async def roles(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        report = await self.bot.roles.ensure_roles(create=True, adopt=True)
        lines = [T.SETUP_ROLES_OK.format(n=len(report.ok))]
        if report.adopted:
            lines.append(T.SETUP_ROLES_ADOPTED.format(names=", ".join(report.adopted)))
        if report.created:
            lines.append(T.SETUP_ROLES_CREATED.format(names=", ".join(report.created)))
        if report.too_high:
            lines.append(T.SETUP_ROLES_TOO_HIGH.format(names=", ".join(report.too_high)))
        unverified = await self.bot.roles.unverified_study_role_holders(report.roles)
        if unverified:
            lines.append(T.SETUP_UNVERIFIED_HOLDERS.format(n=unverified))
        await self.bot.audit.log(
            "setup_roles",
            actor_id=interaction.user.id,
            detail={"created": len(report.created), "adopted": len(report.adopted)},
        )
        await interaction.followup.send("\n".join(lines)[:2000], ephemeral=True)

    @app_commands.command(
        name="panels", description="Poslať panel overenia a panel výberu štúdia do nastavených kanálov"
    )
    @admin_only()
    async def panels(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        posted = []
        panels = (
            ("verify", verify_panel_embed(), VerifyPanelView()),
            ("study_panel", study_panel_embed(), StudyPanelView()),
        )
        for key, embed, view in panels:
            channel = self.bot.resolve_channel(getattr(self.bot.cfg.channels, key))
            if channel is not None:
                await channel.send(embed=embed, view=view)
                posted.append(channel.mention)
        text = T.SETUP_PANELS_POSTED.format(names=", ".join(posted)) if posted else T.SETUP_PANELS_NONE
        await interaction.followup.send(text, ephemeral=True)

    @app_commands.command(name="sync", description="Zaregistrovať slash príkazy na tomto serveri")
    @admin_only()
    async def sync(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = discord.Object(id=self.bot.settings.discord_guild_id)
        self.bot.tree.copy_global_to(guild=guild)
        synced = await self.bot.tree.sync(guild=guild)
        await interaction.followup.send(T.SETUP_SYNCED.format(n=len(synced)), ephemeral=True)

    @app_commands.command(name="reload-config", description="Znovu načítať config.yaml bez reštartu")
    @admin_only()
    async def reload_config(self, interaction: discord.Interaction) -> None:
        try:
            await self.bot.reload_config()
        except (OSError, ValueError, yaml.YAMLError) as exc:
            await interaction.response.send_message(T.SETUP_RELOAD_FAILED.format(error=str(exc)[:1500]), ephemeral=True)
            return
        await self.bot.audit.log("config_reloaded", actor_id=interaction.user.id)
        await interaction.response.send_message(T.SETUP_RELOADED, ephemeral=True)


@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
class AdminCog(commands.GroupCog, group_name="admin", group_description="Správa STUard (admin)"):
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="sso", description="Zapnúť alebo vypnúť prihlásenie cez idp.stuba.sk bez úpravy configu")
    @app_commands.describe(state="Nový stav")
    @app_commands.choices(state=OVERRIDE_CHOICES)
    @admin_only()
    async def sso(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        value = OVERRIDE_VALUES[state.value]
        await self.bot.set_sso_override(value)
        await self.bot.audit.log("sso_override", actor_id=interaction.user.id, detail={"state": state.value})
        text = T.ADMIN_SSO_SET.format(state=state.name, effective=_on_off(self.bot.verification.sso_enabled()))
        if value and self.bot.saml is None:
            text += T.ADMIN_SSO_NO_SAML
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="microsoft", description="Zapnúť alebo vypnúť prihlásenie cez Microsoft 365 (STU)")
    @app_commands.describe(state="Nový stav")
    @app_commands.choices(state=OVERRIDE_CHOICES)
    @admin_only()
    async def microsoft(self, interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        value = OVERRIDE_VALUES[state.value]
        await self.bot.set_microsoft_override(value)
        await self.bot.audit.log("microsoft_override", actor_id=interaction.user.id, detail={"state": state.value})
        text = T.ADMIN_MICROSOFT_SET.format(
            state=state.name, effective=_on_off(self.bot.verification.microsoft_enabled())
        )
        if value and self.bot.microsoft is None:
            text += T.ADMIN_MICROSOFT_NO_APP
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="reverify-status", description="Prehľad ročného obnovenia overenia")
    @admin_only()
    async def reverify_status(self, interaction: discord.Interaction) -> None:
        bot = self.bot
        rc = bot.cfg.reverify
        tz = bot.cfg.tz
        now = now_ts()
        members = await bot.repo.members_with_deadline(rc.applies_to)
        overdue = sum(1 for m in members if m.valid_until is not None and m.valid_until <= now)
        local_now = datetime.now(tz)
        deadline = deadline_for_year(local_now.year, rc, tz)
        if deadline < local_now:
            deadline = deadline_for_year(local_now.year + 1, rc, tz)
        await interaction.response.send_message(
            T.ADMIN_REVERIFY_STATUS.format(
                enabled=_on_off(rc.enabled),
                deadline=deadline.strftime("%d.%m.%Y"),
                count=len(members),
                overdue=overdue,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="reverify-run", description="Spustiť pripomienky a spracovanie po termíne hneď teraz")
    @admin_only()
    async def reverify_run(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        counts = await self.bot.reverify.run()
        await self.bot.audit.log("reverify_manual_run", actor_id=interaction.user.id, detail=counts)
        await interaction.followup.send(T.ADMIN_REVERIFY_RAN.format(**counts), ephemeral=True)


async def setup(bot: StuardBot) -> None:
    await bot.add_cog(SetupCog(bot))
    await bot.add_cog(AdminCog(bot))
