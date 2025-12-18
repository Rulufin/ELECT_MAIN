import discord
from discord.ext import commands
from discord import (
    Interaction,
    User, Member, Message, Role, Guild
)

from utils.ids import *

from typing import Optional
import logging

logger = logging.getLogger(__name__)

FILENAME = "on_reaction_main"

ADMINISTRATOR_IDS = [
    MAIN_ROLES.ADMINISTRATOR_ONE,
    MAIN_ROLES.ADMINISTRATOR_TWO
]

class On_Reaction_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):

        guild_id: Optional[int] = payload.guild_id
        if guild_id is None:
            # DM などギルド外はスキップ
            return

        guild = self.bot.get_guild(guild_id) or await self.bot.fetch_guild(guild_id)
        if guild is None:
            return

        user_id = payload.user_id
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if member is None or member.bot:
            return

        # ADMINISTRATOR_IDS のロールを持っているか
        if not any(role.id in ADMINISTRATOR_IDS for role in member.roles):
            return

        channel_id = payload.channel_id
        if channel_id != MAIN_CHANNELS.PROFILE_PROVISIONAL:
            return

        # チャンネル取得
        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        if channel is None:
            return

        # メッセージ取得（★awaitが必要）
        message_id = payload.message_id
        message = await channel.fetch_message(message_id)

        # 実処理へ
        from on_event.on_reactions.judging import on_reaction_judging
        await on_reaction_judging(guild=guild, message=message)


async def setup(bot: commands.Bot):
    await bot.add_cog(On_Reaction_Main_Cog(bot))