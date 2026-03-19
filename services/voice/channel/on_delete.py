from __future__ import annotations

import logging
import discord

from .context import VoiceChannelContext
from .handlers.flush_and_award import flush_and_award_on_voice_delete

logger = logging.getLogger(__name__)
FILENAME = "voice.channel.on_delete"


async def handle_guild_channel_delete(
    bot: discord.Client,
    channel: discord.abc.GuildChannel,
    ctx: VoiceChannelContext,
) -> None:
    try:
        await flush_and_award_on_voice_delete(bot, channel, ctx)
    except Exception:
        logger.exception(
            "[%s] failed guild_channel_delete ch_id=%s guild_id=%s",
            FILENAME,
            getattr(channel, "id", None),
            getattr(getattr(channel, "guild", None), "id", None),
        )
