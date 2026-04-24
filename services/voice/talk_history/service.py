from __future__ import annotations

import logging
from typing import Optional

from discord import Member, VoiceState

from firestores.fs_talk_history import FS_Talk_History

from .tracker import TalkHistoryTracker, VoiceTrackerConfig
from .rules import (
    should_track_member,
    resolve_countable_state,
    is_same_voice_channel,
    extract_voice_channel_id,
)

logger = logging.getLogger(__name__)
FILENAME = "talk_history.service"


class TalkHistoryService:
    """
    on_voice_state_update から呼ばれる入口。

    役割:
      - member / before / after を受け取る
      - join / leave / move / state_change を判定
      - tracker に処理を渡す
    """

    def __init__(
        self,
        fs_talk_history: Optional[FS_Talk_History] = None,
        *,
        qualify_seconds: float = 300.0,
        flush_seconds: float = 30.0,
        recent_write_ttl: float = 15.0,
        min_write_seconds: float = 1.0,
    ):
        self.fs_talk_history = fs_talk_history or FS_Talk_History(
            qualify_seconds=float(qualify_seconds)
        )
        self.tracker = TalkHistoryTracker(
            self.fs_talk_history,
            config=VoiceTrackerConfig(
                qualify_seconds=float(qualify_seconds),
                flush_seconds=float(flush_seconds),
                recent_write_ttl=float(recent_write_ttl),
                min_write_seconds=float(min_write_seconds),
            ),
        )

    async def handle_voice_state(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> None:
        try:
            before_channel = before.channel
            after_channel = after.channel

            if not should_track_member(member):
                return

            before_vc_id = extract_voice_channel_id(before_channel)
            after_vc_id = extract_voice_channel_id(after_channel)

            before_countable = resolve_countable_state(member, before)
            after_countable = resolve_countable_state(member, after)

            before_category_id = getattr(before_channel, "category_id", None) if before_channel else None
            after_category_id = getattr(after_channel, "category_id", None) if after_channel else None

            if before_vc_id is None and after_vc_id is None:
                return

            if before_vc_id is None and after_vc_id is not None:
                await self.tracker.on_join(
                    vc_id=int(after_vc_id),
                    category_id=int(after_category_id) if after_category_id is not None else None,
                    user_id=int(member.id),
                    countable=bool(after_countable),
                )
                return

            if before_vc_id is not None and after_vc_id is None:
                await self.tracker.on_leave(
                    vc_id=int(before_vc_id),
                    user_id=int(member.id),
                )
                return

            if before_vc_id is not None and after_vc_id is not None:
                if not is_same_voice_channel(before_channel, after_channel):
                    await self.tracker.on_move(
                        before_vc_id=int(before_vc_id),
                        after_vc_id=int(after_vc_id),
                        after_category_id=int(after_category_id) if after_category_id is not None else None,
                        user_id=int(member.id),
                        after_countable=bool(after_countable),
                    )
                    return

            if before_vc_id is not None and after_vc_id is not None:
                if bool(before_countable) != bool(after_countable):
                    await self.tracker.on_state_change(
                        vc_id=int(after_vc_id),
                        user_id=int(member.id),
                        countable=bool(after_countable),
                    )
                return

        except Exception:
            logger.exception(
                "[%s] handle_voice_state failed user_id=%s before_ch=%s after_ch=%s",
                FILENAME,
                getattr(member, "id", None),
                getattr(getattr(before, "channel", None), "id", None),
                getattr(getattr(after, "channel", None), "id", None),
            )

    async def flush_all(self) -> None:
        try:
            await self.tracker.flush_all()
        except Exception:
            logger.exception("[%s] flush_all failed", FILENAME)

    async def flush_vc(
        self,
        *,
        vc_id: int,
    ) -> None:
        try:
            await self.tracker.flush_vc(
                vc_id=int(vc_id),
            )
        except Exception:
            logger.exception(
                "[%s] flush_vc failed vc_id=%s",
                FILENAME,
                vc_id,
            )

    async def remove_user_everywhere(
        self,
        *,
        user_id: int,
    ) -> None:
        try:
            await self.tracker.remove_user_everywhere(user_id=int(user_id))
        except Exception:
            logger.exception(
                "[%s] remove_user_everywhere failed user_id=%s",
                FILENAME,
                user_id,
            )

    async def prune_cache(self) -> None:
        try:
            await self.tracker.prune_stale_recent_writes()
        except Exception:
            logger.exception("[%s] prune_cache failed", FILENAME)

    def snapshot(self) -> dict:
        try:
            return self.tracker.snapshot()
        except Exception:
            logger.exception("[%s] snapshot failed", FILENAME)
            return {
                "vc_count": 0,
                "member_count": 0,
                "pair_count": 0,
            }