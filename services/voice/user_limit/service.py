from __future__ import annotations

import logging

import discord

from services.voice.state.event import VoiceStateContext

logger = logging.getLogger(__name__)

FILENAME = "voice_user_limit_service"


class UserLimitService:
    async def handle_user_limit(self, ctx: VoiceStateContext) -> None:
        """
        bot入退室による user_limit の差分調整。

        - 無制限(0)は触らない
        - bot入室: +1
        - bot退室: -1
        """

        # botイベント以外は対象外
        if not ctx.member.bot:
            return

        # mute切替などは対象外
        if ctx.transition == "NONE":
            return

        targets: dict[int, tuple[discord.VoiceChannel, int]] = {}

        if ctx.transition == "JOIN":
            if ctx.after_ch and not ctx.after_excluded:
                targets[ctx.after_ch.id] = (ctx.after_ch, +1)

        elif ctx.transition == "LEAVE":
            if ctx.before_ch and not ctx.before_excluded:
                targets[ctx.before_ch.id] = (ctx.before_ch, -1)

        elif ctx.transition == "MOVE":
            if ctx.before_ch and not ctx.before_excluded:
                targets[ctx.before_ch.id] = (ctx.before_ch, -1)
            if ctx.after_ch and not ctx.after_excluded:
                targets[ctx.after_ch.id] = (ctx.after_ch, +1)

        for ch, delta in targets.values():
            await self._apply_delta(ch, delta)

    async def _apply_delta(self, ch: discord.VoiceChannel, delta: int) -> None:
        # 無制限は何もしない
        if ch.user_limit == 0:
            return

        old_limit = int(ch.user_limit)
        new_limit = old_limit + int(delta)

        if new_limit < 0:
            new_limit = 0

        if new_limit == old_limit:
            return

        try:
            await ch.edit(
                user_limit=new_limit,
                reason="Adjust user_limit by bot join/leave",
            )
            logger.debug(
                "[%s] ch=%s user_limit %s -> %s (delta=%s)",
                FILENAME,
                ch.id,
                old_limit,
                new_limit,
                delta,
            )
        except (discord.Forbidden, discord.NotFound):
            return
        except discord.HTTPException as e:
            logger.error(
                "[%s] HTTPException ch=%s err=%s",
                FILENAME,
                ch.id,
                e,
                exc_info=True,
            )