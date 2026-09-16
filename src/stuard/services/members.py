"""Member status and teacher flag changes (always audited, always followed by a role sync)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stuard.domain.lifecycle import valid_until
from stuard.timeutil import now_ts, to_dt, to_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot


class MemberService:
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    def valid_until_for(self, status: str, now: int) -> int | None:
        cfg = self.bot.cfg
        if not cfg.reverify.enabled or status not in cfg.reverify.applies_to:
            return None
        return to_ts(valid_until(to_dt(now), cfg.reverify, cfg.tz))

    async def set_status(
        self,
        user_id: int,
        status: str,
        *,
        method: str | None,
        actor_id: int | None = None,
        reason: str | None = None,
        mark_verified: bool = False,
    ) -> None:
        now = now_ts()
        before = await self.bot.repo.get_member(user_id)
        await self.bot.repo.set_member_status(
            user_id,
            status=status,
            method=method,
            now=now,
            valid_until=self.valid_until_for(status, now),
            mark_verified=mark_verified,
        )
        await self.bot.audit.log(
            "status_changed",
            actor_id=actor_id,
            target_id=user_id,
            detail={
                "from": before.status if before else "unverified",
                "to": status,
                "method": method,
                "reason": reason,
            },
        )
        await self.bot.roles.sync_user(user_id, reason=f"STUard: status {status}")

    async def set_teacher(
        self, user_id: int, value: bool, *, actor_id: int | None = None, reason: str | None = None
    ) -> None:
        await self.bot.repo.set_teacher(user_id, value)
        await self.bot.audit.log(
            "teacher_added" if value else "teacher_removed",
            actor_id=actor_id,
            target_id=user_id,
            detail={"reason": reason},
        )
        await self.bot.roles.sync_user(user_id, reason="STUard: Vyučujúci")
