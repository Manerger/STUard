"""GDPR helpers: data export and erasure."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from stuard.timeutil import now_ts

if TYPE_CHECKING:
    from stuard.bot.app import StuardBot

DAY = 86_400


class PrivacyService:
    def __init__(self, bot: StuardBot) -> None:
        self.bot = bot

    async def export(self, user_id: int) -> dict[str, Any]:
        repo = self.bot.repo
        member = await repo.get_member(user_id)
        identity = await repo.get_identity_by_user(user_id)
        study = await repo.get_study(user_id)
        reviews = await repo.reviews_for_user(user_id)
        return {
            "discord_user_id": str(user_id),
            "member": asdict(member) if member else None,
            "uis_identity": (
                {
                    "subject_hmac_sha256": identity.subject_hmac.hex(),
                    "affiliations": identity.affiliations,
                    "bound_at": identity.bound_at,
                    "last_verified_at": identity.last_verified_at,
                }
                if identity
                else None
            ),
            "study_selection": asdict(study) if study else None,
            "review_requests": [
                {
                    "id": r.id,
                    "source": r.source,
                    "claimed_role": r.claimed_role,
                    "sso_affiliations": r.sso_affiliations,
                    "note": r.note,
                    "status": r.status,
                    "decided_role": r.decided_role,
                    "reason": r.reason,
                    "created_at": r.created_at,
                    "decided_at": r.decided_at,
                }
                for r in reviews
            ],
            "audit_log": await repo.audit_for_user(user_id),
            "timestamps": "unix seconds (UTC)",
        }

    async def forget(self, user_id: int) -> None:
        bot = self.bot
        identity = await bot.repo.get_identity_by_user(user_id)
        days = bot.cfg.retention.tombstone_days
        if identity is not None and days > 0:
            await bot.repo.add_tombstone(identity.subject_hmac, now_ts() + days * DAY, user_id)
        await bot.reviews.cancel_for_user(user_id)
        await bot.repo.delete_member(user_id)
        await bot.roles.sync_user(user_id, reason="STUard: /forget-me")
        await bot.audit.log("forget_me", target_id=user_id)
