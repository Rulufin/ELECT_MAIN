import discord
from discord.ext import commands
from discord import (
    Member,
)

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

# ★パスはプロジェクトに合わせて調整してください
from firestores.fs_voice_log import FS_Voice_Log
from firestores.fs_points import FS_Points
from services.points.voice_point_calculator import VoicePointCalculator

from utils.ids import *
from utils.emojis import *

logger = logging.getLogger(__name__)

FILENAME = "on_channel_main"
TIMEZONE = ZoneInfo("Asia/Tokyo")

class on_guild_channel_main_cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_voice_log = FS_Voice_Log()
        self.fs_points = FS_Points()
        self.voice_point_calculator = VoicePointCalculator(self.fs_voice_log, self.fs_points)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if isinstance(channel, discord.VoiceChannel):
            # ここで VC 削除処理
            vc_id = channel.id
            guild_id = channel.guild.id

            # 例：VCログの deleted_at を記録
            await self.fs_voice_log.set_vc_deleted(vc_id=vc_id, deleted_at=datetime.now(TIMEZONE))

            # 集計ロジック呼ぶ（後で作る）
            await self.voice_point_calculator.process_vc_closed(vc_id=vc_id)

async def setup(bot: commands.Bot):
    await bot.add_cog(on_guild_channel_main_cog(bot))