# on_event/on_voice/delete.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord
from discord import VoiceChannel

from on_event.on_voice.context import VoiceStateContext
from utils.ids import MAIN_CATEGORIES

logger = logging.getLogger(__name__)
FILENAME = "delete"

DELETE_CATEGORY_IDS = [
    MAIN_CATEGORIES.PUBLIC_QM, MAIN_CATEGORIES.SECRET_QM,
]

class Delete_Service:
    """
    VCが空（人間0人）になったら削除するサービス。

    - 対象: 指定カテゴリ（例: SECRET_QM_CATEGORY_IDS）配下のVC
    - 発火: LEAVE / MOVE の before_ch 側（= 離脱側）
    - 条件: VC内に human が0人
    - 失敗時: リトライ
    - 追加: 二重削除/直後の再入室に配慮して短い猶予を入れる
    """

    MAX_ATTEMPTS = 3
    RETRY_DELAY = 3.0
    GRACE_SECONDS = 1.5  # 直後に誰か戻る/遅延反映を吸収

    def __init__(self):
        # 「同じVCに対して複数削除を走らせない」ための簡易ガード
        self._inflight: set[int] = set()

    async def handle_delete_flow(self, ctx: VoiceStateContext) -> None:
        try:
            # 除外VCは無視
            if ctx.before_excluded:
                return

            # 離脱側がないなら対象外
            if ctx.before_ch is None:
                return

            # LEAVE/MOVE の離脱側だけ見る
            if ctx.transition not in ("LEAVE", "MOVE"):
                return

            ch = ctx.before_ch

            # 対象カテゴリのみ（必要なら他カテゴリも追加していける）
            if ch.category_id not in DELETE_CATEGORY_IDS:
                return

            # すでに削除処理中なら二重起動しない
            if ch.id in self._inflight:
                return

            self._inflight.add(ch.id)
            try:
                await self._delete_if_empty_with_retry(ch)
            finally:
                self._inflight.discard(ch.id)

        except Exception as e:
            logger.error(f"[{FILENAME}] handle_delete_flow error: {e}", exc_info=True)

    # -------------------------
    # Core
    # -------------------------

    async def _delete_if_empty_with_retry(self, channel: VoiceChannel) -> None:
        # 少し待ってから確認（Discord側の状態反映ズレ対策）
        if self.GRACE_SECONDS > 0:
            await asyncio.sleep(self.GRACE_SECONDS)

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                # もう削除済み/取得不能になってる可能性
                if channel.guild is None:
                    return

                # 「人間がいるなら消さない」
                if any(m for m in channel.members if not m.bot):
                    return

                await channel.delete(reason="Auto-delete empty VC")
                logger.info(f"[{FILENAME}] deleted VC channel={channel.id}")
                return

            except discord.NotFound:
                # 既に消えている
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
