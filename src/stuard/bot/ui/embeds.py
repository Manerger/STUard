from __future__ import annotations

import discord

from stuard import texts as T
from stuard.bot.ui.study_select import study_summary
from stuard.config import AppConfig
from stuard.db.repos import IdentityRow, MemberRow, ReviewRow
from stuard.domain.roleplan import StudySel
from stuard.timeutil import to_dt


def member_embed(
    cfg: AppConfig,
    title: str,
    member: MemberRow | None,
    study: StudySel | None,
    identity: IdentityRow | None,
    *,
    pending: list[ReviewRow] | None = None,
    show_affiliations: bool = False,
) -> discord.Embed:
    embed = discord.Embed(title=title, colour=discord.Colour.blurple())
    status = member.status if member else "unverified"
    embed.add_field(name=T.PROFILE_STATUS, value=T.LABELS.get(status, status))
    embed.add_field(name=T.PROFILE_TEACHER, value=T.YES if member and member.is_teacher else T.NO)
    embed.add_field(name=T.PROFILE_UIS_LINKED, value=T.YES if identity else T.NO)
    if member and member.method:
        embed.add_field(name=T.PROFILE_METHOD, value=T.METHOD_LABELS.get(member.method, member.method), inline=False)
    if member and member.verified_at:
        embed.add_field(name=T.PROFILE_VERIFIED_AT, value=discord.utils.format_dt(to_dt(member.verified_at), "D"))
    if member and member.valid_until:
        embed.add_field(name=T.PROFILE_VALID_UNTIL, value=discord.utils.format_dt(to_dt(member.valid_until), "D"))
    embed.add_field(name=T.PROFILE_STUDY, value=study_summary(cfg, study) or T.PROFILE_NO_STUDY, inline=False)
    if show_affiliations and identity:
        embed.add_field(name=T.REVIEW_FIELD_AFFILIATIONS, value=", ".join(identity.affiliations) or "—", inline=False)
    if pending:
        lines = [f"#{r.id} · {T.REVIEW_TITLES.get(r.source, r.source)}" for r in pending]
        embed.add_field(name=T.MOD_REQUESTS_TITLE, value="\n".join(lines)[:1000], inline=False)
    return embed
