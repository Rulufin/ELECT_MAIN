import logging
from datetime import datetime

from discord.ext import commands
from discord import Member, VoiceState

from firestores.fs_vc_tc_sync import FS_VC_TC_SYNC
from firestores.fs_voice_log import FS_Voice_Log

from services.voice.state.configs import TIMEZONE
from services.voice.state.event import build_context

from services.voice.knock.service import KnockService
from services.voice.voice_log.service import VoiceLogService
from services.voice.user_limit.service import UserLimitService
from services.voice.quick_match.service import QM_Service
from services.voice.delete.service import Delete_Service
from services.voice.talk_history.service import TalkHistoryService
from services.voice.join_notice.registry import build_join_notice_handlers
from services.voice.join_notice.service import JoinNoticeService

logger = logging.getLogger(__name__)

FILENAME = "on_voice_state_main"


class On_Voice_State_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_vc_tc_sync = FS_VC_TC_SYNC()
        self.fs_voice_log = FS_Voice_Log()

        # 実処理系サービス
        self.knock_service = KnockService(fs_vc_tc_sync=self.fs_vc_tc_sync)
        self.qm_service = QM_Service()
        self.voice_log_service = VoiceLogService(fs_voice_log=self.fs_voice_log)
        self.user_limit_service = UserLimitService()
        self.delete_service = Delete_Service()

        self.talk_history_service = TalkHistoryService()
        self.bot.talk_history_service = self.talk_history_service

        self.join_notice_handlers = build_join_notice_handlers()
        self.join_notice_service = JoinNoticeService(
            handlers=self.join_notice_handlers,
            cooldown_seconds=300,
            rejoin_suppress_seconds=60,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ):
        try:
            now = datetime.now(TIMEZONE)

            ctx = build_context(member, before, after, now)
            if ctx is None:
                return

            channel_changed = before.channel != after.channel

            # botの入退室だけ影響する処理
            if channel_changed:
                await self.user_limit_service.handle_user_limit(ctx)

            # 以降は人間ユーザーのみ
            if member.bot:
                return

            # ノック系で処理完結なら後続を止める
            if channel_changed:
                handled = await self.knock_service.handle_knock_flow(ctx)
                if handled:
                    return

                await self.qm_service.handle_qm_flow(ctx)
                await self.delete_service.handle_delete_flow(ctx)

                await self.voice_log_service.log_channel_changes(ctx)
                await self.join_notice_service.handle(member, before, after)

            # talk_history は常に通す
            await self.talk_history_service.handle_voice_state(member, before, after)

            # mute/deaf log も常に通す
            await self.voice_log_service.log_mute_changes(ctx)

        except Exception as e:
            logger.error(f"[{FILENAME}] on_voice_state_update error: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(On_Voice_State_Main_Cog(bot))