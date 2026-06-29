import discord
from discord.ext import commands
from discord import Message

from utils.ids import MAIN_CHANNELS

from firestores.fs_user_info import FS_Profile
from services.message.sleep.service import SleepService
from services.points.post.service import PostPointService

import logging

logger = logging.getLogger(__name__)

FILENAME = "on_message_main"

PROFILE_CHANNELS = [
    MAIN_CHANNELS.PROFILE_MALE,
    MAIN_CHANNELS.PROFILE_FEMALE,
]


class On_Message_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_profile = FS_Profile()
        self.sleep_service = SleepService()
        self.post_point_service = PostPointService()

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        author = message.author

        if author.bot:
            return

        if message.guild is None:
            return

        channel = message.channel

        if channel.id == MAIN_CHANNELS.SLEEP_MENTION:
            await self.sleep_service.handle_sleep_mention(message)
            return

        if channel.id in PROFILE_CHANNELS:
            await self.fs_profile.add_profile_data(
                author_id=author.id,
                author_name=author.display_name,
                message_id=message.id,
            )

        await self.post_point_service.grant_post_points(message)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return

        await self.post_point_service.revoke_post_points_raw(
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            message_id=payload.message_id,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(On_Message_Main_Cog(bot))