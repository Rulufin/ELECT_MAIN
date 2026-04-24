from __future__ import annotations

import logging
from typing import Optional

from discord import Member, VoiceState

from firestores.fs_judging_temp import FS_Judging_Temp
from services.voice.join_notice.base import BaseJoinNoticeHandler
from utils.ids import MAIN_ROLES

logger = logging.getLogger(__name__)

FILENAME = "temp_judge_join_notice"


class TempJudgeJoinNoticeHandler(BaseJoinNoticeHandler):
    def __init__(self):
        self.fs_judging_temp = FS_Judging_Temp()

    def _has_temp_member_role(self, member: Member) -> bool:
        return any(role.id == MAIN_ROLES.P_MEMBER for role in member.roles)

    async def should_send(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> bool:
        return self._has_temp_member_role(member)

    async def build_content(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> Optional[str]:
        latest_entry = await self.fs_judging_temp.get_latest_entry_for_target(member.id)
        if not latest_entry:
            logger.info("[%s] latest entry not found user_id=%s", FILENAME, member.id)
            return None

        user_thread_id = latest_entry.get("user_thread_id")
        if not user_thread_id:
            logger.info("[%s] user_thread_id not found user_id=%s", FILENAME, member.id)
            return None

        try:
            thread_id = int(user_thread_id)
        except (TypeError, ValueError):
            logger.warning("[%s] invalid user_thread_id=%s", FILENAME, user_thread_id)
            return None

        guild = member.guild
        thread = guild.get_channel(thread_id)
        if thread is None:
            try:
                thread = await guild.fetch_channel(thread_id)
            except Exception:
                logger.exception(
                    "[%s] failed to fetch thread user_id=%s thread_id=%s",
                    FILENAME,
                    member.id,
                    thread_id,
                )
                return None

        jump_url = getattr(thread, "jump_url", None)
        if not jump_url:
            logger.warning("[%s] jump_url missing thread_id=%s", FILENAME, thread_id)
            return None

        return (
            f"{member.mention}\n"
            f"仮免審査スレッドはこちらです。\n"
            f"{jump_url}"
        )