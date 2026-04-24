from __future__ import annotations

import asyncio
import logging

import discord
from discord import VoiceChannel

from on_event.on_voice.context import VoiceStateContext
from utils.ids import MAIN_CATEGORIES

logger = logging.getLogger(__name__)

FILENAME = "voice_delete_service"

DELETE_CATEGORY_IDS = [
    MAIN_CATEGORIES.PUBLIC_QM,
    MAIN_CATEGORIES.SECRET_QM,
]


class Delete_Service:
    """
    VCが空（人間0人）になったら削除するサービス。

    - 対象: 指定カテゴリ配下のVC
    - 発火: LEAVE / MOVE の before_ch 側（= 離脱側）
    - 条件: VC内に human が0人
    - 失敗時: リトライ
    - 二重削除/直後の再入室に配慮して短い猶予を入れる
    """

    MAX_ATTEMPTS = 3
    RETRY_DELAY = 3.0
    GRACE_SECONDS = 1.5

    def __init__(self):
        # 同じVCに対する多重削除防止
        self._inflight: set[int] = set()

    async def handle_delete_flow(self, ctx: VoiceStateContext) -> None:
        try:
            # 除外VCは無視
            if ctx.before_excluded:
                return

            # 離脱側がなければ対象外
            if ctx.before_ch is None:
                return

            # LEAVE / MOVE の離脱側のみ対象
            if ctx.transition not in ("LEAVE", "MOVE"):
                return

            ch = ctx.before_ch

            # 対象カテゴリのみ削除
            if ch.category_id not in DELETE_CATEGORY_IDS:
                return

            # 同じVCに対する二重起動を防ぐ
            if ch.id in self._inflight:
                return

            self._inflight.add(ch.id)
            try:
                await self._delete_if_empty_with_retry(ch)
            finally:
                self._inflight.discard(ch.id)

        except Exception as e:
            logger.error(f"[{FILENAME}] handle_delete_flow error: {e}", exc_info=True)

    async def _delete_if_empty_with_retry(self, channel: VoiceChannel) -> None:
        # Discord側の反映遅延や即再入室を吸収
        if self.GRACE_SECONDS > 0:
            await asyncio.sleep(self.GRACE_SECONDS)

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                if channel.guild is None:
                    return

                # botを除く人間がまだいるなら削除しない
                if any(member for member in channel.members if not member.bot):
                    return

                await channel.delete(reason="Auto-delete empty VC")
                logger.info(f"[{FILENAME}] deleted VC channel={channel.id}")
                return

            except discord.NotFound:
                # 既に削除済み
                return

            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(
                    f"[{FILENAME}] delete failed channel={channel.id} "
                    f"attempt={attempt}/{self.MAX_ATTEMPTS}: {e}",
                    exc_info=True,
                )

                if attempt < self.MAX_ATTEMPTS:
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue

                return