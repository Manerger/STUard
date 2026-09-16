"""Moderator reviews: manual screenshots and logins that need a human decision."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

import discord

from stuard import texts as T
from stuard.bot.ui.review_items import review_view
from stuard.db.repos import ReviewRow
from stuard.timeutil import now_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

log = logging.getLogger(__name__)

DAY = 86_400
MAX_MANUAL_REQUESTS_PER_30_DAYS = 5
# Button action code → role granted on approval.
APPROVE_ACTIONS: dict[str, str] = {"st": "student", "ap": "applicant", "te": "teacher", "al": "alumni"}
ACTION_FOR_ROLE: dict[str, str] = {role: code for code, role in APPROVE_ACTIONS.items()}
SOURCE_ACTIONS: dict[str, tuple[str, ...]] = {
    "manual": ("st", "ap", "te", "al"),
    "sso_status": ("st", "ap", "al"),
    "sso_teacher": ("te",),
}
IMAGE_TYPES: dict[str, str] = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class ReviewService:
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    def _channel(self) -> discord.TextChannel | discord.Thread | None:
        return self.bot.resolve_channel(self.bot.cfg.channels.mod_review)

    def _embed(
        self,
        review_id: int,
        source: str,
        user_id: int,
        member: discord.Member | None,
        *,
        role: str | None = None,
        note: str | None = None,
        affiliations: Iterable[str] | None = None,
        via: str | None = None,
        login: str | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(title=T.REVIEW_TITLES[source], colour=discord.Colour.orange())
        embed.add_field(name=T.REVIEW_FIELD_MEMBER, value=f"<@{user_id}> (`{user_id}`)", inline=False)
        if member is not None:
            embed.add_field(name=T.REVIEW_FIELD_ACCOUNT_AGE, value=discord.utils.format_dt(member.created_at, "R"))
        if role:
            name = T.REVIEW_FIELD_CLAIMED if source == "manual" else T.REVIEW_FIELD_SUGGESTION
            embed.add_field(name=name, value=T.LABELS.get(role, role))
        if via:
            embed.add_field(name=T.REVIEW_FIELD_VIA, value=T.VIA_LABELS.get(via, via))
        if login:
            embed.add_field(name=T.REVIEW_FIELD_LOGIN, value=f"`{login}`")
        if affiliations is not None:
            label = T.REVIEW_FIELD_EMPLOYEE_TYPE if via == "microsoft" else T.REVIEW_FIELD_AFFILIATIONS
            embed.add_field(name=label, value=", ".join(sorted(affiliations)) or "—", inline=False)
        if note:
            embed.add_field(name=T.REVIEW_FIELD_NOTE, value=note[:1000], inline=False)
        embed.set_footer(text=T.REVIEW_FOOTER.format(id=review_id))
        return embed

    # ------------------------------------------------------------------ creation
    async def submit_manual(
        self, member: discord.Member, claimed_role: str, attachment: discord.Attachment, note: str | None
    ) -> str:
        bot = self.bot
        cfg = bot.cfg.manual
        now = now_ts()
        if not bot.verification.manual_available():
            return T.MANUAL_DISABLED
        if claimed_role not in ACTION_FOR_ROLE:
            return T.REVIEW_ACTION_INVALID
        content_type = (attachment.content_type or "").split(";")[0].strip().lower()
        if content_type not in IMAGE_TYPES or attachment.size > cfg.max_bytes:
            return T.MANUAL_BAD_FILE.format(mb=cfg.max_bytes // 1_000_000)

        existing = await bot.repo.get_member(member.id)
        if existing is not None and (
            (claimed_role == "teacher" and existing.is_teacher) or existing.status == claimed_role
        ):
            return T.MANUAL_ALREADY_VERIFIED.format(role=T.LABELS[claimed_role])
        if await bot.repo.pending_review(member.id, "manual"):
            return T.MANUAL_ALREADY_PENDING
        last_rejected = await bot.repo.last_decision_at(member.id, "manual", "rejected")
        cooldown = cfg.reject_cooldown_hours * 3600
        if last_rejected is not None and now - last_rejected < cooldown:
            hours = max(1, round((cooldown - (now - last_rejected)) / 3600))
            return T.MANUAL_COOLDOWN.format(hours=hours)
        if await bot.repo.count_reviews_since(member.id, "manual", now - 30 * DAY) >= MAX_MANUAL_REQUESTS_PER_30_DAYS:
            return T.MANUAL_TOO_MANY
        channel = self._channel()
        if channel is None:
            return T.MANUAL_NOT_CONFIGURED

        review_id = await bot.repo.create_review(member.id, "manual", now, claimed_role=claimed_role, note=note)
        if review_id is None:
            return T.MANUAL_ALREADY_PENDING
        try:
            # The image goes from memory straight to the private channel; it is never written to disk.
            data = await attachment.read()
            file = discord.File(
                io.BytesIO(data), filename=f"review-{review_id}.{IMAGE_TYPES[content_type]}", spoiler=True
            )
            message = await channel.send(
                embed=self._embed(review_id, "manual", member.id, member, role=claimed_role, note=note),
                file=file,
                view=review_view(review_id, SOURCE_ACTIONS["manual"]),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            log.exception("could not post manual review #%s", review_id)
            await bot.repo.decide_review(review_id, status="cancelled", decided_by=None, now=now_ts())
            return T.GENERIC_ERROR
        await bot.repo.set_review_message(review_id, channel.id, message.id)
        await bot.audit.log(
            "review_created", target_id=member.id, detail={"id": review_id, "source": "manual", "claimed": claimed_role}
        )
        return T.MANUAL_SUBMITTED

    async def open_sso_review(
        self,
        user_id: int,
        source: str,
        affiliations: Iterable[str],
        *,
        suggest: str | None,
        login: str | None = None,
        via: str = "saml",
    ) -> bool:
        """Create (or keep) a pending review after a successful login. Returns True if a review is pending.

        `affiliations` are idp.stuba.sk affiliations or the Microsoft 365 account type. `login` is shown only in the
        moderator message (deleted after the decision), never stored.
        """
        bot = self.bot
        affs = sorted(affiliations)
        if await bot.repo.pending_review(user_id, source):
            return True
        review_id = await bot.repo.create_review(user_id, source, now_ts(), claimed_role=suggest, sso_affiliations=affs)
        if review_id is None:
            return True
        channel = self._channel()
        if channel is None:
            log.warning("channels.mod_review is not configured; review #%s is only listed in /mod requests", review_id)
        else:
            guild = bot.guild
            member = guild.get_member(user_id) if guild else None
            embed = self._embed(
                review_id, source, user_id, member, role=suggest, affiliations=affs, via=via, login=login
            )
            try:
                message = await channel.send(
                    embed=embed,
                    view=review_view(review_id, SOURCE_ACTIONS[source]),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await bot.repo.set_review_message(review_id, channel.id, message.id)
            except discord.HTTPException:
                log.exception("could not post review #%s", review_id)
        await bot.audit.log("review_created", target_id=user_id, detail={"id": review_id, "source": source, "via": via})
        return True

    # ------------------------------------------------------------------ decisions
    async def handle_action(self, interaction: discord.Interaction, review_id: int, action: str) -> None:
        from stuard.bot.ui.review_items import RejectModal

        bot = self.bot
        if not isinstance(interaction.user, discord.Member) or not bot.is_moderator(interaction.user):
            await interaction.response.send_message(T.NO_PERMISSION, ephemeral=True)
            return
        review = await bot.repo.get_review(review_id)
        if review is None or review.status != "pending":
            await interaction.response.send_message(T.REVIEW_ALREADY_DECIDED, ephemeral=True)
            return
        if review.user_id == interaction.user.id:
            await interaction.response.send_message(T.REVIEW_SELF, ephemeral=True)
            return
        if action == "rej":
            await interaction.response.send_modal(RejectModal(review_id))
            return
        if action not in SOURCE_ACTIONS.get(review.source, ()):
            await interaction.response.send_message(T.REVIEW_ACTION_INVALID, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.decide(review, interaction.user.id, approved_role=APPROVE_ACTIONS[action], reason=None)
        await interaction.followup.send(result, ephemeral=True)

    async def reject_from_modal(self, interaction: discord.Interaction, review_id: int, reason: str) -> None:
        bot = self.bot
        if not isinstance(interaction.user, discord.Member) or not bot.is_moderator(interaction.user):
            await interaction.response.send_message(T.NO_PERMISSION, ephemeral=True)
            return
        review = await bot.repo.get_review(review_id)
        if review is None or review.status != "pending":
            await interaction.response.send_message(T.REVIEW_ALREADY_DECIDED, ephemeral=True)
            return
        if review.user_id == interaction.user.id:
            await interaction.response.send_message(T.REVIEW_SELF, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.decide(review, interaction.user.id, approved_role=None, reason=reason.strip())
        await interaction.followup.send(result, ephemeral=True)

    async def decide(
        self, review: ReviewRow, moderator_id: int, *, approved_role: str | None, reason: str | None
    ) -> str:
        bot = self.bot
        now = now_ts()
        status = "approved" if approved_role else "rejected"
        if not await bot.repo.decide_review(
            review.id, status=status, decided_by=moderator_id, now=now, decided_role=approved_role, reason=reason
        ):
            return T.REVIEW_ALREADY_DECIDED
        if approved_role == "teacher":
            await bot.repo.set_teacher(review.user_id, True)
        elif approved_role is not None:
            await bot.repo.set_member_status(
                review.user_id,
                status=approved_role,
                # Login-based reviews keep the method recorded at login (sso or microsoft).
                method="manual" if review.source == "manual" else None,
                now=now,
                valid_until=bot.members.valid_until_for(approved_role, now),
                mark_verified=True,
            )
        await bot.roles.sync_user(review.user_id, reason=f"STUard: žiadosť #{review.id}")
        await self.delete_message(review)
        await bot.audit.log(
            f"review_{status}",
            actor_id=moderator_id,
            target_id=review.user_id,
            detail={"id": review.id, "source": review.source, "role": approved_role, "reason": reason},
        )
        guild_name = bot.guild.name if bot.guild else "server"
        if approved_role is not None:
            text = T.DM_APPROVED.format(guild=guild_name, role=T.LABELS[approved_role])
            if approved_role == "student":
                text += T.DM_APPROVED_STUDENT_HINT
            await bot.dm(review.user_id, text)
            return T.REVIEW_APPROVED.format(member=f"<@{review.user_id}>", role=T.LABELS[approved_role])
        await bot.dm(review.user_id, T.DM_REJECTED.format(guild=guild_name, reason=reason or "—"))
        return T.REVIEW_REJECTED.format(member=f"<@{review.user_id}>")

    async def delete_message(self, review: ReviewRow) -> None:
        if not (review.channel_id and review.message_id):
            return
        channel = self.bot.get_channel(review.channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread):
            return
        try:
            await channel.get_partial_message(review.message_id).delete()
        except discord.NotFound:
            pass
        except discord.HTTPException:
            log.warning("could not delete review message %s", review.message_id)

    async def expire_pending(self) -> int:
        bot = self.bot
        now = now_ts()
        expired = 0
        guild_name = bot.guild.name if bot.guild else "server"
        for review in await bot.repo.pending_reviews_before(now - bot.cfg.manual.expire_days * DAY):
            if not await bot.repo.decide_review(review.id, status="expired", decided_by=None, now=now):
                continue
            await self.delete_message(review)
            await bot.audit.log("review_expired", target_id=review.user_id, detail={"id": review.id}, notify=False)
            if review.source == "manual":
                await bot.dm(review.user_id, T.DM_EXPIRED.format(guild=guild_name))
            expired += 1
        return expired

    async def cancel_for_user(self, user_id: int) -> None:
        now = now_ts()
        for review in await self.bot.repo.reviews_for_user(user_id):
            if review.status == "pending" and await self.bot.repo.decide_review(
                review.id, status="cancelled", decided_by=None, now=now
            ):
                await self.delete_message(review)
