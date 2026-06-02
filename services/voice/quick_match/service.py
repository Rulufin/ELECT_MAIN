from __future__ import annotations

import asyncio
import logging

import discord
from discord import Member, PermissionOverwrite, VoiceChannel

from services.voice.state.event import VoiceStateContext
from utils.ids import MAIN_CATEGORIES, MAIN_ROLES

logger = logging.getLogger(__name__)

FILENAME = "voice_quick_match_service"

SECRET_QM_CATEGORY_IDS = [
    MAIN_CATEGORIES.SECRET_QM,
]


class QM_Service:
    """
    Secret QMカテゴリのVCで、2人揃ったタイミングで部屋をクローズするサービス。

    - 対象: after_ch.category_id in SECRET_QM_CATEGORY_IDS
    - 条件: 人間が2人以上（必要なら ==2 に変更可）
    - 動作:
        * @everyone は基本閉じる
        * member / p_member / male / p_male / female / p_female を deny
        * VC内の人間に view/connect/speak を許可
    - 失敗時: リトライ
    """

    MAX_ATTEMPTS = 3
    RETRY_DELAY = 3.0

    DENY_EVERYONE = True
    REQUIRE_EXACTLY_TWO = False

    async def handle_qm_flow(self, ctx: VoiceStateContext) -> None:
        try:
            if ctx.after_excluded:
                return

            if ctx.after_ch is None:
                return

            if ctx.transition not in ("JOIN", "MOVE"):
                return

            ch = ctx.after_ch
            if ch.category_id not in SECRET_QM_CATEGORY_IDS:
                return

            if ctx.member.bot:
                return

            await self._maybe_close_secret_qm_room(ch)

        except Exception as e:
            logger.error(f"[{FILENAME}] handle_qm_flow error: {e}", exc_info=True)

    async def _maybe_close_secret_qm_room(self, channel: VoiceChannel) -> None:
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
        ow_map = channel.overwrites

        member_role = channel.guild.get_role(MAIN_ROLES.MEMBER)
        if member_role is None:
            return False

        role_ow = ow_map.get(member_role)
        if not (role_ow and role_ow.view_channel is False and role_ow.connect is False):
            return False

        for member in humans:
            member_ow = ow_map.get(member)
            if not (member_ow and member_ow.view_channel is True and member_ow.connect is True):
                return False

        return True

    async def _apply_close_overwrites(self, channel: VoiceChannel, humans: list[Member]) -> None:
        guild = channel.guild

        member_role = guild.get_role(MAIN_ROLES.MEMBER) or await guild.fetch_role(MAIN_ROLES.MEMBER)
        p_member_role = guild.get_role(MAIN_ROLES.P_MEMBER) or await guild.fetch_role(MAIN_ROLES.P_MEMBER)
        male_role = guild.get_role(MAIN_ROLES.MALE) or await guild.fetch_role(MAIN_ROLES.MALE)
        p_male_role = guild.get_role(MAIN_ROLES.P_MALE) or await guild.fetch_role(MAIN_ROLES.P_MALE)
        female_role = guild.get_role(MAIN_ROLES.FEMALE) or await guild.fetch_role(MAIN_ROLES.FEMALE)
        p_female_role = guild.get_role(MAIN_ROLES.P_FEMALE) or await guild.fetch_role(MAIN_ROLES.P_FEMALE)

        deny_roles = [
            role
            for role in (
                member_role,
                p_member_role,
                male_role,
                p_male_role,
                female_role,
                p_female_role,
            )
            if role is not None
        ]

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
                overwrites = channel.overwrites.copy()

                for target in list(overwrites.keys()):
                    if isinstance(target, Member):
                        overwrites.pop(target, None)

                if self.DENY_EVERYONE:
                    overwrites[guild.default_role] = deny_ow

                for role in deny_roles:
                    overwrites[role] = deny_ow

                for member in humans:
                    overwrites[member] = allow_ow

                await channel.edit(
                    overwrites=overwrites,
                    user_limit=0,
                    reason="QM: close secret room",
                )

                mentions = " ".join(member.mention for member in humans)
                await channel.send(
                    content=f"{mentions}\nVCをクローズしました。"
                )
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