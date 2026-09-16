"""Audit trail: stored in the database and mirrored (text only) to the audit channel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord

from stuard.timeutil import now_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

log = logging.getLogger(__name__)


def _fmt(value: Any) -> str:
    if isinstance(value, list | tuple | set | frozenset):
        return ", ".join(str(v) for v in sorted(value, key=str)) or "—"
    return str(value)


class AuditService:
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    async def log(
        self,
        action: str,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        detail: dict[str, Any] | None = None,
        notify: bool = True,
    ) -> None:
        """Never pass UIS logins, names or screenshots in `detail`."""
        clean = {k: v for k, v in (detail or {}).items() if v is not None}
        try:
            await self.bot.repo.add_audit(now_ts(), action, actor_id, target_id, clean or None)
        except Exception:
            log.exception("failed to store audit entry %s", action)
        log.info("audit %s actor=%s target=%s %s", action, actor_id, target_id, clean)
        if notify:
            await self._post(action, actor_id, target_id, clean)

    async def _post(self, action: str, actor_id: int | None, target_id: int | None, detail: dict[str, Any]) -> None:
        channel = self.bot.resolve_channel(self.bot.cfg.channels.audit)
        if channel is None:
            return
        parts = [f"**{action}**"]
        if target_id:
            parts.append(f"člen <@{target_id}>")
        if actor_id:
            parts.append(f"od <@{actor_id}>")
        if detail:
            parts.append("; ".join(f"{k}: {_fmt(v)}" for k, v in detail.items()))
        try:
            await channel.send(" · ".join(parts)[:1900], allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.warning("could not post to the audit channel")
