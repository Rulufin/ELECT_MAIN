from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from discord import Member, VoiceState

from firestores.fs_voice_log import FS_Voice_Log
from on_event.on_voice.context import VoiceStateContext
from on_event.on_voice.configs import NOT_CONNECT_VC_IDS

logger = logging.getLogger(__name__)

FILENAME = "voice_log_service"


class VoiceLogService:
    """
    VC の JOIN / LEAVE / MOVE / MUTE を Firestore に記録するサービス。
    """

    def __init__(self, fs_voice_log: Optional[FS_Voice_Log] = None):
        self.fs_voice_log = fs_voice_log or FS_Voice_Log()

    async def _ensure_owner_if_target_vc(self, *, vc_id: int, owner_user_id: int) -> None:
        """
        対象VCの場合のみ、owner_user_id が空なら保存する。
        """
        if vc_id in NOT_CONNECT_VC_IDS:
            return
        await self.fs_voice_log.set_vc_owner_if_empty(
            vc_id=vc_id,
            owner_user_id=owner_user_id,
        )

    async def log_channel_changes(self, ctx: VoiceStateContext) -> None:
        member: Member = ctx.member
        guild = ctx.guild
        before_ch = ctx.before_ch
        after_ch = ctx.after_ch
        now = ctx.now

        before_excluded = ctx.before_excluded
        after_excluded = ctx.after_excluded

        try:
            # ---- JOIN ----
            if before_ch is None and after_ch is not None:
                if after_excluded:
                    return

                after_vs: VoiceState = ctx.after

                await self.fs_voice_log.ensure_vc_doc(
                    vc_id=after_ch.id,
                    guild_id=guild.id,
                    created_at=now,
                    category_id=after_ch.category_id,
                )

                await self._ensure_owner_if_target_vc(
                    vc_id=after_ch.id,
                    owner_user_id=member.id,
                )

                extra: Dict[str, Any] = {
                    "guild_id": str(guild.id),
                    "category_id": str(after_ch.category_id),
                    "from_channel_id": None,
                    "to_channel_id": str(after_ch.id),
                    "is_self_mute": after_vs.self_mute,
                    "is_self_deaf": after_vs.self_deaf,
                    "is_server_mute": after_vs.mute,
                    "is_server_deaf": after_vs.deaf,
                }

                await self.fs_voice_log.add_event(
                    vc_id=after_ch.id,
                    user_id=member.id,
                    event_type="JOIN",
                    ts=now,
                    extra=extra,
                )

                logger.info(
                    "[%s] JOIN user=%s vc=%s category_id=%s",
                    FILENAME,
                    member.id,
                    after_ch.id,
                    after_ch.category_id,
                )
                return

            # ---- LEAVE ----
            if before_ch is not None and after_ch is None:
                if before_excluded:
                    return

                before_vs: VoiceState = ctx.before

                await self.fs_voice_log.ensure_vc_doc(
                    vc_id=before_ch.id,
                    guild_id=guild.id,
                    created_at=now,
                    category_id=before_ch.category_id,
                )

                extra: Dict[str, Any] = {
                    "guild_id": str(guild.id),
                    "category_id": str(before_ch.category_id),
                    "from_channel_id": str(before_ch.id),
                    "to_channel_id": None,
                    "is_self_mute": before_vs.self_mute,
                    "is_self_deaf": before_vs.self_deaf,
                    "is_server_mute": before_vs.mute,
                    "is_server_deaf": before_vs.deaf,
                }

                await self.fs_voice_log.add_event(
                    vc_id=before_ch.id,
                    user_id=member.id,
                    event_type="LEAVE",
                    ts=now,
                    extra=extra,
                )

                logger.info(
                    "[%s] LEAVE user=%s vc=%s category_id=%s",
                    FILENAME,
                    member.id,
                    before_ch.id,
                    before_ch.category_id,
                )
                return

            # ---- MOVE ----
            if before_ch is not None and after_ch is not None and before_ch.id != after_ch.id:
                before_vs: VoiceState = ctx.before
                after_vs: VoiceState = ctx.after

                if before_excluded and after_excluded:
                    return

                # 除外 -> 対象 は JOIN のみ
                if before_excluded and not after_excluded:
                    await self.fs_voice_log.ensure_vc_doc(
                        vc_id=after_ch.id,
                        guild_id=guild.id,
                        created_at=now,
                        category_id=after_ch.category_id,
                    )

                    await self._ensure_owner_if_target_vc(
                        vc_id=after_ch.id,
                        owner_user_id=member.id,
                    )

                    extra = {
                        "guild_id": str(guild.id),
                        "category_id": str(after_ch.category_id),
                        "from_channel_id": str(before_ch.id),
                        "to_channel_id": str(after_ch.id),
                        "is_self_mute": after_vs.self_mute,
                        "is_self_deaf": after_vs.self_deaf,
                        "is_server_mute": after_vs.mute,
                        "is_server_deaf": after_vs.deaf,
                    }

                    await self.fs_voice_log.add_event(
                        vc_id=after_ch.id,
                        user_id=member.id,
                        event_type="JOIN",
                        ts=now,
                        extra=extra,
                    )
                    return

                # 対象 -> 除外 は LEAVE のみ
                if not before_excluded and after_excluded:
                    await self.fs_voice_log.ensure_vc_doc(
                        vc_id=before_ch.id,
                        guild_id=guild.id,
                        created_at=now,
                        category_id=before_ch.category_id,
                    )

                    extra = {
                        "guild_id": str(guild.id),
                        "category_id": str(before_ch.category_id),
                        "from_channel_id": str(before_ch.id),
                        "to_channel_id": str(after_ch.id),
                        "is_self_mute": before_vs.self_mute,
                        "is_self_deaf": before_vs.self_deaf,
                        "is_server_mute": before_vs.mute,
                        "is_server_deaf": before_vs.deaf,
                    }

                    await self.fs_voice_log.add_event(
                        vc_id=before_ch.id,
                        user_id=member.id,
                        event_type="LEAVE",
                        ts=now,
                        extra=extra,
                    )
                    return

                # 両方対象
                await self.fs_voice_log.ensure_vc_doc(
                    vc_id=before_ch.id,
                    guild_id=guild.id,
                    created_at=now,
                    category_id=before_ch.category_id,
                )
                await self.fs_voice_log.ensure_vc_doc(
                    vc_id=after_ch.id,
                    guild_id=guild.id,
                    created_at=now,
                    category_id=after_ch.category_id,
                )

                await self._ensure_owner_if_target_vc(
                    vc_id=after_ch.id,
                    owner_user_id=member.id,
                )

                await self.fs_voice_log.add_event(
                    vc_id=before_ch.id,
                    user_id=member.id,
                    event_type="LEAVE",
                    ts=now,
                    extra={
                        "guild_id": str(guild.id),
                        "category_id": str(before_ch.category_id),
                        "from_channel_id": str(before_ch.id),
                        "to_channel_id": str(after_ch.id),
                        "is_self_mute": before_vs.self_mute,
                        "is_self_deaf": before_vs.self_deaf,
                        "is_server_mute": before_vs.mute,
                        "is_server_deaf": before_vs.deaf,
                    },
                )

                await self.fs_voice_log.add_event(
                    vc_id=after_ch.id,
                    user_id=member.id,
                    event_type="JOIN",
                    ts=now,
                    extra={
                        "guild_id": str(guild.id),
                        "category_id": str(after_ch.category_id),
                        "from_channel_id": str(before_ch.id),
                        "to_channel_id": str(after_ch.id),
                        "is_self_mute": after_vs.self_mute,
                        "is_self_deaf": after_vs.self_deaf,
                        "is_server_mute": after_vs.mute,
                        "is_server_deaf": after_vs.deaf,
                    },
                )
                return

        except Exception as e:
            logger.error(f"[{FILENAME}] log_channel_changes error: {e}", exc_info=True)

    async def log_mute_changes(self, ctx: VoiceStateContext) -> None:
        member: Member = ctx.member
        before: VoiceState = ctx.before
        after: VoiceState = ctx.after
        now = ctx.now
        guild = ctx.guild

        try:
            def effective(vs: VoiceState) -> bool:
                return vs.self_mute or vs.self_deaf or vs.mute or vs.deaf

            before_eff = effective(before)
            after_eff = effective(after)

            current_ch = ctx.after_ch or ctx.before_ch
            if current_ch is None:
                return

            if current_ch.id in NOT_CONNECT_VC_IDS:
                return

            if before_eff == after_eff:
                return

            await self.fs_voice_log.ensure_vc_doc(
                vc_id=current_ch.id,
                guild_id=guild.id,
                created_at=now,
                category_id=current_ch.category_id,
            )

            extra = {
                "guild_id": str(guild.id),
                "category_id": str(current_ch.category_id),
                "is_self_mute": after.self_mute,
                "is_self_deaf": after.self_deaf,
                "is_server_mute": after.mute,
                "is_server_deaf": after.deaf,
            }

            if after_eff:
                await self.fs_voice_log.add_event(
                    vc_id=current_ch.id,
                    user_id=member.id,
                    event_type="MUTE_ON",
                    ts=now,
                    extra=extra,
                )
            else:
                await self.fs_voice_log.add_event(
                    vc_id=current_ch.id,
                    user_id=member.id,
                    event_type="MUTE_OFF",
                    ts=now,
                    extra=extra,
                )

        except Exception as e:
            logger.error(f"[{FILENAME}] log_mute_changes error: {e}", exc_info=True)