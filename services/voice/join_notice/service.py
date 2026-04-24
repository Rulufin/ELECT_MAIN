from __future__ import annotations

import logging
import time

from discord import Member, VoiceState

from services.voice.join_notice.base import BaseJoinNoticeHandler

logger = logging.getLogger(__name__)

FILENAME = "voice_join_notice_service"


class JoinNoticeService:
    def __init__(
        self,
        handlers: list[BaseJoinNoticeHandler] | None = None,
        cooldown_seconds: int = 300,
        rejoin_suppress_seconds: int = 60,
    ):
        self.handlers = handlers or []
        self.cooldown_seconds = cooldown_seconds
        self.rejoin_suppress_seconds = rejoin_suppress_seconds

        # key: (handler_name, guild_id, user_id, channel_id)
        self._recent_sent: dict[tuple[str, int, int, int], float] = {}

        # key: (guild_id, user_id)
        self._recent_leave: dict[tuple[int, int], float] = {}

    def add_handler(self, handler: BaseJoinNoticeHandler) -> None:
        self.handlers.append(handler)

    def _is_join_or_move_to_vc(
        self,
        before: VoiceState,
        after: VoiceState,
    ) -> bool:
        if after.channel is None:
            return False

        if before.channel is None and after.channel is not None:
            return True

        if (
            before.channel is not None
            and after.channel is not None
            and before.channel.id != after.channel.id
        ):
            return True

        return False

    def _is_leave_from_vc(
        self,
        before: VoiceState,
        after: VoiceState,
    ) -> bool:
        return before.channel is not None and after.channel is None

    def _mark_leave(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> None:
        self._recent_leave[(guild_id, user_id)] = time.time()

    def _is_recent_rejoin(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> bool:
        last_leave = self._recent_leave.get((guild_id, user_id))
        if last_leave is None:
            return False

        return (time.time() - last_leave) < self.rejoin_suppress_seconds

    def _is_on_cooldown(
        self,
        *,
        handler_name: str,
        guild_id: int,
        user_id: int,
        channel_id: int,
    ) -> bool:
        now = time.time()
        key = (handler_name, guild_id, user_id, channel_id)
        last_sent = self._recent_sent.get(key)

        if last_sent is not None and (now - last_sent) < self.cooldown_seconds:
            return True

        return False

    def _mark_sent(
        self,
        *,
        handler_name: str,
        guild_id: int,
        user_id: int,
        channel_id: int,
    ) -> None:
        key = (handler_name, guild_id, user_id, channel_id)
        self._recent_sent[key] = time.time()

    def _cleanup_old_entries(self) -> None:
        now = time.time()

        recent_sent_keep = max(self.cooldown_seconds, self.rejoin_suppress_seconds) + 60
        self._recent_sent = {
            key: ts
            for key, ts in self._recent_sent.items()
            if (now - ts) < recent_sent_keep
        }

        recent_leave_keep = self.rejoin_suppress_seconds + 60
        self._recent_leave = {
            key: ts
            for key, ts in self._recent_leave.items()
            if (now - ts) < recent_leave_keep
        }

    async def handle(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ) -> None:
        if member.bot:
            return

        guild_id = member.guild.id
        user_id = member.id

        self._cleanup_old_entries()

        # 退出時刻を記録
        if self._is_leave_from_vc(before, after):
            self._mark_leave(guild_id=guild_id, user_id=user_id)
            return

        # join / move 以外は無視
        if not self._is_join_or_move_to_vc(before, after):
            return

        channel = after.channel
        if channel is None:
            return

        # 退出→再入室が短時間なら通知しない
        if self._is_recent_rejoin(guild_id=guild_id, user_id=user_id):
            logger.info(
                "[%s] skip join notice by recent rejoin guild_id=%s user_id=%s channel_id=%s",
                FILENAME,
                guild_id,
                user_id,
                channel.id,
            )
            return

        channel_id = channel.id

        for handler in self.handlers:
            handler_name = handler.__class__.__name__

            if self._is_on_cooldown(
                handler_name=handler_name,
                guild_id=guild_id,
                user_id=user_id,
                channel_id=channel_id,
            ):
                continue

            try:
                sent = await handler.send(member, before, after)
                if sent:
                    self._mark_sent(
                        handler_name=handler_name,
                        guild_id=guild_id,
                        user_id=user_id,
                        channel_id=channel_id,
                    )
            except Exception:
                logger.exception(
                    "[%s] join notice failed handler=%s guild_id=%s user_id=%s channel_id=%s",
                    FILENAME,
                    handler_name,
                    guild_id,
                    user_id,
                    channel_id,
                )