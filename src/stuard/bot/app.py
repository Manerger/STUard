"""The bot process: Discord client, services, web server and background jobs on one event loop."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from stuard import texts as T
from stuard.bot.ui.panels import StudyPanelView, VerifyPanelView
from stuard.bot.ui.review_items import ReviewButton
from stuard.config import AppConfig, load_config
from stuard.db.connection import connect
from stuard.db.migrate import migrate
from stuard.db.repos import Repo
from stuard.security.ratelimit import RateLimiter
from stuard.services.audit import AuditService
from stuard.services.email_verify import EmailVerifyService
from stuard.services.members import MemberService
from stuard.services.privacy import PrivacyService
from stuard.services.reverify import ReverifyService
from stuard.services.review import ReviewService
from stuard.services.roles import RoleService
from stuard.services.verification import VerificationService
from stuard.settings import Settings
from stuard.web.discord_oauth import DiscordOAuth
from stuard.web.microsoft import MicrosoftSignIn, load_microsoft
from stuard.web.saml_sp import SamlSP, load_saml
from stuard.web.server import WebServer

log = logging.getLogger(__name__)

EXTENSIONS = (
    "stuard.bot.cogs.verify",
    "stuard.bot.cogs.profile",
    "stuard.bot.cogs.moderation",
    "stuard.bot.cogs.setup",
    "stuard.bot.cogs.privacy",
    "stuard.bot.cogs.events",
)
SSO_OVERRIDE_KEY = "sso_enabled_override"
MICROSOFT_OVERRIDE_KEY = "microsoft_enabled_override"
EMAIL_OVERRIDE_KEY = "email_enabled_override"
MANUAL_OVERRIDE_KEY = "manual_enabled_override"


class StuardBot(commands.Bot):
    repo: Repo

    def __init__(self, settings: Settings, cfg: AppConfig) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.settings = settings
        self.cfg = cfg
        self.saml: SamlSP | None = None
        self.microsoft: MicrosoftSignIn | None = None
        self.oauth: DiscordOAuth | None = None
        self.sso_override: bool | None = None
        self.microsoft_override: bool | None = None
        self.email_override: bool | None = None
        self.manual_override: bool | None = None
        self.web: WebServer | None = None
        self.verify_limiter = RateLimiter(3, 15 * 60)
        self.web_limiter = RateLimiter(30, 60)

        self.audit = AuditService(self)
        self.roles = RoleService(self)
        self.members = MemberService(self)
        self.reviews = ReviewService(self)
        self.email = EmailVerifyService(self)
        self.verification = VerificationService(self)
        self.reverify = ReverifyService(self)
        self.privacy = PrivacyService(self)
        self.tree.error(self._on_app_command_error)

    @property
    def guild(self) -> discord.Guild | None:
        return self.get_guild(self.settings.discord_guild_id)

    async def setup_hook(self) -> None:
        conn = await connect(self.settings.database_path)
        await migrate(conn)
        self.repo = Repo(conn)
        self.sso_override = await self._load_override(SSO_OVERRIDE_KEY)
        self.microsoft_override = await self._load_override(MICROSOFT_OVERRIDE_KEY)
        self.email_override = await self._load_override(EMAIL_OVERRIDE_KEY)
        self.manual_override = await self._load_override(MANUAL_OVERRIDE_KEY)

        self.saml = load_saml(self.settings, self.cfg)
        self.microsoft = load_microsoft(self.settings, self.cfg)
        secret = self.settings.discord_client_secret.get_secret_value()
        if self.settings.discord_client_id and secret:
            self.oauth = DiscordOAuth(
                self.settings.discord_client_id, secret, f"{self.settings.public_base_url}/oauth/discord/callback"
            )

        self.add_dynamic_items(ReviewButton)
        self.add_view(VerifyPanelView())
        self.add_view(StudyPanelView())
        for extension in EXTENSIONS:
            await self.load_extension(extension)

        guild = discord.Object(id=self.settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        if self.settings.sync_commands:
            synced = await self.tree.sync(guild=guild)
            log.info("synced %d slash commands to guild %s", len(synced), guild.id)

        self.web = WebServer(self, self.settings.web_host, self.settings.web_port)
        await self.web.start()
        verification = self.verification
        log.info(
            "login methods: STU (idp.stuba.sk) %s, Microsoft 365 %s, email code %s, manual review %s",
            *(
                "on" if on else "off"
                for on in (
                    verification.sso_enabled(),
                    verification.microsoft_enabled(),
                    self.email.enabled(),
                    verification.manual_available(),
                )
            ),
        )

    async def close(self) -> None:
        if self.web is not None:
            await self.web.stop()
            self.web = None
        await super().close()
        repo = getattr(self, "repo", None)
        if repo is not None:
            del self.repo
            await repo.close()

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            message = T.NO_PERMISSION
        else:
            log.error("slash command failed", exc_info=error)
            message = T.GENERIC_ERROR
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ helpers used by services and cogs
    def is_admin(self, member: discord.Member) -> bool:
        return member.guild_permissions.administrator or any(r.id in self.cfg.admin_role_ids for r in member.roles)

    def is_moderator(self, member: discord.Member) -> bool:
        allowed = set(self.cfg.moderator_role_ids) | set(self.cfg.admin_role_ids)
        return self.is_admin(member) or any(r.id in allowed for r in member.roles)

    def resolve_channel(self, ref: int | str | None) -> discord.TextChannel | discord.Thread | None:
        """A configured channel: an ID, or a text channel name such as admin_room_verifikacie."""
        if ref is None:
            return None
        if isinstance(ref, int):
            channel = self.get_channel(ref)
        else:
            guild = self.guild
            wanted = ref.casefold()
            channel = next((c for c in guild.text_channels if c.name.casefold() == wanted), None) if guild else None
        return channel if isinstance(channel, discord.TextChannel | discord.Thread) else None

    def describe_user(self, user_id: int) -> tuple[str, str | None]:
        user = self.get_user(user_id)
        if user is None:
            return f"ID {user_id}", None
        avatar = user.display_avatar.replace(size=128, static_format="png").url
        return f"{user.display_name} (@{user.name})", avatar

    async def dm(self, user_id: int, text: str) -> bool:
        try:
            user = self.get_user(user_id) or await self.fetch_user(user_id)
            await user.send(text)
        except discord.HTTPException:
            return False
        return True

    async def _load_override(self, key: str) -> bool | None:
        stored = await self.repo.get_setting(key)
        return None if stored is None else stored == "1"

    async def _store_override(self, key: str, value: bool | None) -> None:
        await self.repo.set_setting(key, None if value is None else ("1" if value else "0"))

    async def set_sso_override(self, value: bool | None) -> None:
        await self._store_override(SSO_OVERRIDE_KEY, value)
        self.sso_override = value

    async def set_microsoft_override(self, value: bool | None) -> None:
        await self._store_override(MICROSOFT_OVERRIDE_KEY, value)
        self.microsoft_override = value

    async def set_email_override(self, value: bool | None) -> None:
        await self._store_override(EMAIL_OVERRIDE_KEY, value)
        self.email_override = value

    async def set_manual_override(self, value: bool | None) -> None:
        await self._store_override(MANUAL_OVERRIDE_KEY, value)
        self.manual_override = value

    async def reload_config(self) -> None:
        cfg = load_config(self.settings.config_path)
        saml = load_saml(self.settings, cfg)
        microsoft = load_microsoft(self.settings, cfg)
        self.cfg = cfg
        self.saml = saml
        self.microsoft = microsoft
        self.roles.invalidate()
