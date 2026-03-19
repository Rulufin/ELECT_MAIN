# utils/discord/fetch.py
from __future__ import annotations

from typing import Optional

import discord

from .safe_call import safe_call


async def get_or_fetch_member(guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
    m = guild.get_member(user_id)
    if m is not None:
        return m

    return await safe_call(
        lambda: guild.fetch_member(user_id),
        action="guild.fetch_member",
        use_queue=False,
        swallow_forbidden=True,
        swallow_not_found=True,
    )


async def get_or_fetch_channel(bot: discord.Client, channel_id: int) -> Optional[discord.abc.GuildChannel | discord.Thread]:
    ch = bot.get_channel(channel_id)
    if ch is not None:
        return ch  # type: ignore[return-value]

    return await safe_call(
        lambda: bot.fetch_channel(channel_id),
        action="client.fetch_channel",
        use_queue=False,
        swallow_forbidden=True,
        swallow_not_found=True,
    )


async def get_or_fetch_message(channel: discord.abc.Messageable, message_id: int) -> Optional[discord.Message]:
    # TextChannel/Thread has get_partial_message but no cache access without channel.history.
    # Best effort: use fetch_message if available.
    fetch = getattr(channel, "fetch_message", None)
    if fetch is None:
        return None

    return await safe_call(
        lambda: fetch(message_id),
        action="channel.fetch_message",
        use_queue=False,
        swallow_forbidden=True,
        swallow_not_found=True,
    )
