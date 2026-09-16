"""Yearly re-verification job: reminders before the deadline, status change after it."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from stuard import texts as T
from stuard.domain.lifecycle import cycle_id, due_reminders, expired_status
from stuard.timeutil import now_ts, to_dt

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot


class ReverifyService:
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    async def run(self) -> dict[str, int]:
        bot = self.bot
        rc = bot.cfg.reverify
        counts = {"reminded": 0, "expired": 0}
        if not rc.enabled:
            return counts
        tz = bot.cfg.tz
        now = now_ts()
        now_dt = to_dt(now)
        guild_name = bot.guild.name if bot.guild else "server"

        for member in await bot.repo.members_with_deadline(rc.applies_to):
            if member.valid_until is None:
                continue
            deadline = to_dt(member.valid_until).astimezone(tz)
            if now >= member.valid_until:
                new_status = expired_status(member.status, rc)
                if new_status is None:
                    continue
                await bot.repo.set_member_status(
                    member.user_id, status=new_status, method=None, now=now, valid_until=None, mark_verified=False
                )
                await bot.audit.log(
                    "reverify_expired",
                    target_id=member.user_id,
                    detail={"from": member.status, "to": new_status},
                    notify=False,
                )
                await bot.roles.sync_user(member.user_id, reason="STUard: overenie vypršalo")
                if member.left_at is None:
                    await bot.dm(
                        member.user_id,
                        T.REVERIFY_EXPIRED_DM.format(guild=guild_name, status=T.LABELS[new_status]),
                    )
                counts["expired"] += 1
                await asyncio.sleep(1)  # stay well below Discord's role-edit rate limits
                continue

            if member.left_at is not None:
                continue
            cycle = cycle_id(deadline)
            sent = {
                int(kind[1:])
                for kind in await bot.repo.sent_reminders(member.user_id, cycle)
                if kind.startswith("d") and kind[1:].isdigit()
            }
            due = due_reminders(now_dt, deadline, rc.reminders_days_before, sent)
            if not due:
                continue
            await bot.dm(
                member.user_id, T.REVERIFY_REMINDER.format(guild=guild_name, deadline=deadline.strftime("%d.%m.%Y"))
            )
            await bot.repo.record_reminders(member.user_id, cycle, [f"d{d}" for d in due], now)
            counts["reminded"] += 1
            await asyncio.sleep(0.5)

        if counts["expired"] or counts["reminded"]:
            await bot.audit.log("reverify_run", detail=counts)
        return counts
