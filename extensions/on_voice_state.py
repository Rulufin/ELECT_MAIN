import logging
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands
from discord import Member, VoiceState

from firestores.fs_vc_tc_sync import FS_VC_TC_SYNC
from firestores.fs_voice_log import FS_Voice_Log

from on_event.on_voice.configs import TIMEZONE
from on_event.on_voice.context import build_context
from on_event.on_voice.knock import KnockService
from on_event.on_voice.logger import VoiceLogService
from on_event.on_voice.user_limit import UserLimitService
from on_event.on_voice.quick_match import QM_Service
from on_event.on_voice.delete import Delete_Service

logger = logging.getLogger(__name__)

FILENAME = "on_voice_state_main"

class On_Voice_State_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_vc_tc_sync = FS_VC_TC_SYNC()
        self.fs_voice_log = FS_Voice_Log()

        # ノック関連のサービス
        self.knock_service = KnockService(fs_vc_tc_sync=self.fs_vc_tc_sync)
        # QM関連のサービス
        self.qm_service = QM_Service()

        # VC_LOG への書き込みサービス
        self.voice_log_service = VoiceLogService(fs_voice_log=self.fs_voice_log)
        self.user_limit_service = UserLimitService()

        self.delete_service = Delete_Service()

    # -------------------------
    # イベント本体
    # -------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ):
        """
        VCの接続・切断・移動、およびミュート状態の変化を Firestore に記録する。

        記録対象:
        - JOIN:   before.channel is None, after.channel is not None
        - LEAVE:  before.channel is not None, after.channel is None
        - MOVE:   両方 not None かつ channel.id が変化 → LEAVE + JOIN
        - MUTE_ON / MUTE_OFF: effective_mute の変化時のみ

        ただし NOT_CONNECT_VC_IDS に含まれるVCはログ対象から除外する。
        """
        try:
            now = datetime.now(TIMEZONE)

            ctx = build_context(member, before, after, now)
            if ctx is None:
                return

            await self.user_limit_service.handle_user_limit(ctx)

            if member.bot:
                return

            handled = await self.knock_service.handle_knock_flow(ctx)
            if handled:
                return

            await self.qm_service.handle_qm_flow(ctx)

            # ★追加：削除（ログより前/後どっちでもいいが、後だと消えた後参照に注意）
            await self.delete_service.handle_delete_flow(ctx)

            await self.voice_log_service.log_channel_changes(ctx)
            await self.voice_log_service.log_mute_changes(ctx)

        except Exception as e:
            logger.error(f"[{FILENAME}] on_voice_state_update error: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(On_Voice_State_Main_Cog(bot))
