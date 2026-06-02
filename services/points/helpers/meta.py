from __future__ import annotations

from typing import Any, Iterable, Optional

import discord
from discord import Interaction

from utils.discord.safe_calls.interaction import safe_followup_send


async def send_ephemeral_error(interaction: Interaction, content: str) -> None:
    await safe_followup_send(interaction=interaction, content=content, ephemeral=True)


def build_points_meta(
    *,
    interaction: Interaction,
    code: str,
    price: int,
    target_user_ids: Optional[Iterable[int]] = None,
    thread_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "price": price,
        "executor_id": interaction.user.id,
        "target_user_ids": list(target_user_ids) if target_user_ids is not None else None,
        "thread_id": thread_id,
        "channel_id": channel_id,
        "guild_id": interaction.guild.id if interaction.guild else None,
    }
