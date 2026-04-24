import discord
from discord.ext import commands

from discord import VoiceChannel, StageChannel

from datetime import datetime
from zoneinfo import ZoneInfo
import logging

from firestores.fs_voice_log import FS_Voice_Log
from firestores.fs_points import FS_Points
from services.points.voice.calculator import VoicePointCalculator

logger = logging.getLogger(__name__)

FILENAME = "on_channel_main"
TIMEZONE = ZoneInfo("Asia/Tokyo")


class on_guild_channel_main_cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_voice_log = FS_Voice_Log()
        self.fs_points = FS_Points()
        self.voice_point_calculator = VoicePointCalculator(
            self.fs_voice_log,
            self.fs_points,
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not isinstance(channel, (VoiceChannel, StageChannel)):
            return

        try:
            vc_id = channel.id

            await self.fs_voice_log.set_vc_deleted(
                vc_id=vc_id,
                deleted_at=datetime.now(TIMEZONE),
            )

            talk_history_service = getattr(self.bot, "talk_history_service", None)
            if talk_history_service is not None:
                await talk_history_service.flush_vc(
                    vc_id=vc_id,
                )

            await self.voice_point_calculator.process_vc_closed(vc_id=vc_id)

        except Exception:
            logger.exception(
                "[%s] on_guild_channel_delete failed guild_id=%s vc_id=%s",
                FILENAME,
                getattr(getattr(channel, "guild", None), "id", None),
                getattr(channel, "id", None),
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(on_guild_channel_main_cog(bot))