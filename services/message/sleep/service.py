from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import Message, Member, VoiceChannel

from utils.ids import MAIN_CHANNELS
from utils.emojis import DEFAULT

logger = logging.getLogger(__name__)

FILENAME = "sleep_service"


class SleepService:
    def __init__(self):
        pass

    async def handle_sleep_mention(self, message: Message) -> None:
        guild = message.guild
        author = message.author

        if guild is None:
            return

        if not isinstance(author, Member):
            return

        # 呼び出した本人がVCにいない
        if author.voice is None or author.voice.channel is None:
            await message.add_reaction("❌")
            return

        sleep_vc = await self._resolve_sleep_vc(guild)

        if sleep_vc is None:
            await message.add_reaction("❌")
            return

        mentioned_members = [
            member for member in message.mentions
            if isinstance(member, Member)
        ]

        if not mentioned_members:
            return

        moved = False
        author_vc = author.voice.channel

        for member in mentioned_members:
            if member.voice is None or member.voice.channel is None:
                continue

            # 同じVCにいない人は対象外
            if member.voice.channel.id != author_vc.id:
                await message.add_reaction("❌")
                continue

            try:
                await member.move_to(
                    sleep_vc,
                    reason="寝落ちVCへ移動",
                )
                moved = True

            except discord.Forbidden:
                logger.warning(
                    "[%s] move forbidden member_id=%s",
                    FILENAME,
                    member.id,
                )

            except discord.HTTPException:
                logger.exception(
                    "[%s] move failed member_id=%s",
                    FILENAME,
                    member.id,
                )

            except Exception:
                logger.exception(
                    "[%s] unexpected move error member_id=%s",
                    FILENAME,
                    member.id,
                )

        if moved:
            await message.add_reaction(f"{DEFAULT.SLEEP}")
        else:
            await message.add_reaction("❌")

    async def _resolve_sleep_vc(self, guild: discord.Guild) -> Optional[VoiceChannel]:
        channel = guild.get_channel(MAIN_CHANNELS.SLEEP_VC)

        if channel is None:
            try:
                channel = await guild.fetch_channel(MAIN_CHANNELS.SLEEP_VC)
            except discord.HTTPException:
                logger.exception("[%s] sleep vc fetch failed", FILENAME)
                return None

        if not isinstance(channel, VoiceChannel):
            return None

        return channel