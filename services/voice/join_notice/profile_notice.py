from __future__ import annotations

import logging
from typing import Optional

from discord import Member, VoiceState, Embed

from firestores.fs_user_info import FS_Profile
from firestores.fs_judging_temp import FS_Judging_Temp
from services.voice.join_notice.base import BaseJoinNoticeHandler
from services.system.embeds import Profile_Embed
from utils.ids import MAIN_ROLES, MAIN_CHANNELS

logger = logging.getLogger(__name__)

FILENAME = "profile_join_notice"


class ProfileJoinNoticeHandler(BaseJoinNoticeHandler):

    def __init__(self):
        self.fs_profile = FS_Profile()
        self.fs_judging_temp = FS_Judging_Temp()

    # ─────────────────────────
    # role 判定
    # ─────────────────────────

    def _has_role(self, member: Member, role_id: int) -> bool:
        return any(role.id == role_id for role in member.roles)

    def _is_provisional_member(self, member: Member) -> bool:
        return self._has_role(member, MAIN_ROLES.P_MEMBER)

    # ─────────────────────────
    # profile channel 判定
    # ─────────────────────────

    def _resolve_profile_channel_id(self, member: Member) -> int | None:

        role_ids = {role.id for role in member.roles}

        if MAIN_ROLES.P_MALE in role_ids:
            return MAIN_CHANNELS.PROFILE_MALE

        if MAIN_ROLES.P_FEMALE in role_ids:
            return MAIN_CHANNELS.PROFILE_FEMALE

        if MAIN_ROLES.MALE in role_ids:
            return MAIN_CHANNELS.PROFILE_MALE

        if MAIN_ROLES.FEMALE in role_ids:
            return MAIN_CHANNELS.PROFILE_FEMALE

        return None

    # ─────────────────────────
    # handler 実行判定
    # ─────────────────────────

    async def should_send(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> bool:
        return self._resolve_profile_channel_id(member) is not None

    # ─────────────────────────
    # profile URL
    # ─────────────────────────

    async def _build_profile_url(
        self,
        member: Member,
    ) -> Optional[str]:

        channel_id = self._resolve_profile_channel_id(member)
        if channel_id is None:
            return None

        profile_data = await self.fs_profile.get_profile_data(str(member.id))

        if not profile_data:
            logger.info("[%s] profile not found user_id=%s", FILENAME, member.id)
            return None

        message_id = profile_data.get("MESSAGE_ID")
        if not message_id:
            return None

        try:
            message_id = int(message_id)
        except Exception:
            return None

        guild = member.guild

        return (
            f"https://discord.com/channels/"
            f"{guild.id}/{channel_id}/{message_id}"
        )

    # ─────────────────────────
    # 仮免審査 thread URL
    # ─────────────────────────

    async def _build_temp_judge_thread_url(
        self,
        member: Member,
    ) -> Optional[str]:

        if not self._is_provisional_member(member):
            return None

        latest_entry = await self.fs_judging_temp.get_latest_entry_for_target(member.id)

        if not latest_entry:
            return None

        thread_id = latest_entry.get("user_thread_id")

        if not thread_id:
            return None

        try:
            thread_id = int(thread_id)
        except Exception:
            return None

        guild = member.guild

        thread = guild.get_channel(thread_id)

        if thread is None:
            try:
                thread = await guild.fetch_channel(thread_id)
            except Exception:
                logger.exception(
                    "[%s] failed fetch thread user_id=%s thread_id=%s",
                    FILENAME,
                    member.id,
                    thread_id,
                )
                return None

        return getattr(thread, "jump_url", None)

    # ─────────────────────────
    # Embed生成
    # ─────────────────────────

    async def build_embed(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> Optional[Embed]:

        profile_url = await self._build_profile_url(member)
        thread_url = await self._build_temp_judge_thread_url(member)

        if not profile_url and not thread_url:
            return None

        return Profile_Embed(
            target=member,
            profile_url=profile_url,
            thread_url=thread_url,
        )