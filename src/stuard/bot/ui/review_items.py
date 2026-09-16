"""Review buttons that survive bot restarts (custom_id carries the review id and action)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import discord

from stuard import texts as T

ACTION_ROLES: dict[str, str] = {"st": "student", "ap": "applicant", "te": "teacher", "al": "alumni"}


class ReviewButton(
    discord.ui.DynamicItem[discord.ui.Button[Any]],
    template=r"stuard:rv:(?P<id>\d+):(?P<action>st|ap|te|al|rej)",
):
    def __init__(self, review_id: int, action: str) -> None:
        if action == "rej":
            label, style = T.REVIEW_REJECT, discord.ButtonStyle.danger
        else:
            label, style = T.REVIEW_APPROVE.format(role=T.LABELS[ACTION_ROLES[action]]), discord.ButtonStyle.success
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"stuard:rv:{review_id}:{action}"))
        self.review_id = review_id
        self.action = action

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button[Any], match: re.Match[str], /
    ) -> ReviewButton:
        return cls(int(match["id"]), match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        client: Any = interaction.client
        await client.reviews.handle_action(interaction, self.review_id, self.action)


def review_view(review_id: int, approve_actions: Iterable[str]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action in approve_actions:
        view.add_item(ReviewButton(review_id, action))
    view.add_item(ReviewButton(review_id, "rej"))
    return view


class RejectModal(discord.ui.Modal):
    reason: discord.ui.TextInput[RejectModal] = discord.ui.TextInput(
        label=T.REVIEW_REJECT_REASON, style=discord.TextStyle.paragraph, min_length=3, max_length=500
    )

    def __init__(self, review_id: int) -> None:
        super().__init__(title=T.REVIEW_REJECT_MODAL_TITLE, timeout=600)
        self.review_id = review_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        client: Any = interaction.client
        await client.reviews.reject_from_modal(interaction, self.review_id, self.reason.value)
