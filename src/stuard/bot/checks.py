from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import discord
from discord import app_commands

T = TypeVar("T")


def moderator_only() -> Callable[[T], T]:
    async def predicate(interaction: discord.Interaction) -> bool:
        client: Any = interaction.client
        return isinstance(interaction.user, discord.Member) and client.is_moderator(interaction.user)

    return app_commands.check(predicate)


def admin_only() -> Callable[[T], T]:
    async def predicate(interaction: discord.Interaction) -> bool:
        client: Any = interaction.client
        return isinstance(interaction.user, discord.Member) and client.is_admin(interaction.user)

    return app_commands.check(predicate)
