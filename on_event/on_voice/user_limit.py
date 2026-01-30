# on_event/on_voice/user_limit.py
from __future__ import annotations

import logging
import discord

from on_event.on_voice.context import VoiceStateContext

logger = logging.getLogger(__name__)


class UserLimitService:
    async def handle_user_limit(self, ctx: VoiceStateContext) -> None:
        """
        bot入退室による user_limit の差分調整。
        - 無制限(0)は触らない
        - bot入室: +1
        - bot退室: -1
        """

        # botイベント以外は対象外（人の入退室で limit を触らない方針ならここで弾く）
        if not ctx.member.bot:
            return

        # 変化がない（mute切替など）なら対象なし
        if ctx.transition == "NONE":
            return

        # 変更対象VCと差分を決める
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

        # 反映
        for ch, delta in targets.values():
            await self._apply_delta(ch, delta)

    async def _apply_delta(self, ch: discord.VoiceChannel, delta: int) -> None:
        # 無制限は何もしない
        if ch.user_limit == 0:
            return

        new_limit = ch.user_limit + delta
        if new_limit < 0:
            new_limit = 0

        if new_limit == ch.user_limit:
            return

        try:
            await ch.edit(
                user_limit=new_limit,
                reason="Adjust user_limit by bot join/leave",
            )
            logger.debug(f"[UserLimit] ch={ch.id} user_limit {ch.user_limit} -> {new_limit} (delta={delta})")
        except (discord.Forbidden, discord.NotFound):
            # 権限なし / 既に消えてる等：ここは静かに抜ける
            return
        except discord.HTTPException as e:
            logger.error(f"[UserLimit] HTTPException: ch={ch.id} err={e}", exc_info=True)
