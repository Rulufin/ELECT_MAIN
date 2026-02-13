# on_event/on_voice/quick_match.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord
from discord import (
    Member, Guild, PermissionOverwrite,
    VoiceChannel,
)

from on_event.on_voice.context import VoiceStateContext
from utils.ids import MAIN_ROLES, MAIN_CATEGORIES  # あなたの定数に合わせて

logger = logging.getLogger(__name__)
FILENAME = "quick_match"

SECRET_QM_CATEGORY_IDS = [
    MAIN_CATEGORIES.SECRET_QM
]

class QM_Service:
    """
    Secret QMカテゴリのVCで、2人揃ったタイミングで部屋をクローズ（ロールをdeny / 現在の人間だけallow）

    - 対象: after_ch.category_id in SECRET_QM_CATEGORY_IDS
    - 条件: 人間が2人以上（必要なら ==2 に変更可）
    - 動作:
        * @everyone は基本閉じる（DENY_EVERYONE=True）
        * member/male/p_male/female/p_female を view/connect 不可
        * VC内の人間に view/connect/speak 許可
    - 失敗時: リトライ
    - VC削除は delete.py に寄せるのでここではやらない
    """

    MAX_ATTEMPTS = 3
    RETRY_DELAY = 3.0

    # @everyone も閉じるか（あなたの運用に合わせて）
    DENY_EVERYONE = True

    # 「2人揃ったら」: ==2 が厳密。3人でも閉じたいなら >=2。
    REQUIRE_EXACTLY_TWO = False  # True にすると "ちょうど2人" の時だけクローズ

    async def handle_qm_flow(self, ctx: VoiceStateContext) -> None:
        try:
            # 除外VCは無視（contextで判定済み）
            if ctx.after_excluded:
                return

            # after側がない（LEAVEなど）なら何もしない
            if ctx.after_ch is None:
                return

            # JOIN/MOVE の after側のみ対象
            if ctx.transition not in ("JOIN", "MOVE"):
                return

            ch = ctx.after_ch
            if ch.category_id not in SECRET_QM_CATEGORY_IDS:
                return

            # botは上流で弾いてるが、念のため
            if ctx.member.bot:
                return

            await self._maybe_close_secret_qm_room(ch)

        except Exception as e:
            logger.error(f"[{FILENAME}] handle_qm_flow error: {e}", exc_info=True)

    # -------------------------
    # Core
    # -------------------------

    async def _maybe_close_secret_qm_room(self, channel: VoiceChannel) -> None:
        """
        VC内の人間が条件を満たすなら、権限をロックする。
        """
        # 現在の人間メンバー
        humans = [m for m in channel.members if not m.bot]

        if self.REQUIRE_EXACTLY_TWO:
            if len(humans) != 2:
                return
        else:
            if len(humans) < 2:
                return

        if self._is_already_closed(channel, humans):
            return

        await self._apply_close_overwrites(channel, humans)

    def _is_already_closed(self, channel: VoiceChannel, humans: list[Member]) -> bool:
        ow_map = channel.overwrites  # dict[Snowflake, PermissionOverwrite]

        # 1) ロールが閉じてるか（最低条件）
        member_role = channel.guild.get_role(MAIN_ROLES.MEMBER)
        if member_role is None:
            return False

        r_ow = ow_map.get(member_role)
        if not (r_ow and r_ow.view_channel is False and r_ow.connect is False):
            return False

        # 2) 今いる人間全員が allow を持ってるか（閉じた後の形）
        for m in humans:
            m_ow = ow_map.get(m)
            if not (m_ow and m_ow.view_channel is True and m_ow.connect is True):
                return False

        return True

    async def _apply_close_overwrites(self, channel: VoiceChannel, humans: list[Member]) -> None:
        guild = channel.guild

        # roles
        member_role   = guild.get_role(MAIN_ROLES.MEMBER)   or await guild.fetch_role(MAIN_ROLES.MEMBER)
        p_member_role = guild.get_role(MAIN_ROLES.P_MEMBER) or await guild.fetch_role(MAIN_ROLES.P_MEMBER)
        male_role     = guild.get_role(MAIN_ROLES.MALE)     or await guild.fetch_role(MAIN_ROLES.MALE)
        p_male_role   = guild.get_role(MAIN_ROLES.P_MALE)   or await guild.fetch_role(MAIN_ROLES.P_MALE)
        female_role   = guild.get_role(MAIN_ROLES.FEMALE)   or await guild.fetch_role(MAIN_ROLES.FEMALE)
        p_female_role = guild.get_role(MAIN_ROLES.P_FEMALE) or await guild.fetch_role(MAIN_ROLES.P_FEMALE)

        deny_roles = [r for r in (member_role, p_member_role, male_role, p_male_role, female_role, p_female_role) if r is not None]

        deny_ow = PermissionOverwrite(
            view_channel=False,
            connect=False,
        )

        allow_ow = PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
        )

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                # 現状の上書きをベースに編集
                overwrites = channel.overwrites.copy()

                # 既存の個人上書きを一旦削除（「今いる人だけ」に寄せる）
                for target in list(overwrites.keys()):
                    if isinstance(target, Member):
                        overwrites.pop(target, None)

                # @everyone も閉じる
                if self.DENY_EVERYONE:
                    overwrites[guild.default_role] = deny_ow

                # 指定ロールを閉じる
                for r in deny_roles:
                    overwrites[r] = deny_ow

                # 今いる人間だけ開ける
                for m in humans:
                    overwrites[m] = allow_ow

                await channel.edit(overwrites=overwrites, user_limit=0, reason="QM: close secret room")

                mentions = " ".join(m.mention for m in humans)
                
                await channel.send(content=f"{mentions}\nVCをクローズしました。")
                return

            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning(
                    f"[{FILENAME}] overwrite apply failed channel={channel.id} "
                    f"attempt={attempt}/{self.MAX_ATTEMPTS}: {e}",
                    exc_info=True,
                )
                if attempt < self.MAX_ATTEMPTS:
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                return