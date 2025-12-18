import discord
from discord.ext import commands
from discord import (
    Interaction,
    User, Member, Message, Role, Guild, VoiceChannel
)

from utils.ids import *
from utils.emojis import *

from firestores.fs_user_info import FS_Profile

import logging

logger = logging.getLogger(__name__)

FILENAME = "on_message_main"

PROFILE_CHANNELS = [
    
]

class On_Message_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_profile = FS_Profile()

    @commands.Cog.listener()
    async def on_message(self, message: Message):

        author = message.author

        if author.bot:
            return
        
        channel = message.channel
        guild = message.guild

        if guild is None:
            return

        # ─────────────────────────────
        # 対象チャンネル
        # ─────────────────────────────
        if channel.id == MAIN_CHANNELS.SLEEP_MENTION:

            # 呼び出した本人がそもそもVCにいないなら使えない
            if not author.voice:
                await message.add_reaction("❌")
                return

            # 寝落ちVCを取得
            sleep_vc: VoiceChannel = guild.get_channel(MAIN_CHANNELS.SLEEP_VC) or await guild.fetch_channel(
                MAIN_CHANNELS.SLEEP_VC
            )

            if not isinstance(sleep_vc, VoiceChannel):
                await message.add_reaction("❌")
                return

            # メッセージ内のメンション取得
            mentioned_members = message.mentions

            if not mentioned_members:
                await message.add_reaction("❌")
                return

            moved = False

            for member in mentioned_members:
                if not member.voice:
                    # VCにいないので移動できない
                    continue

                try:
                    await member.move_to(sleep_vc, reason="寝落ちVC召喚")
                    moved = True
                except Exception:
                    pass

            if moved:
                await message.add_reaction(f"{DEFAULT.SLEEP}")
            else:
                await message.add_reaction("❌")

        if channel.id in PROFILE_CHANNELS:
            await self.fs_profile.add_profile_data(author_id=author.id, author_name=author.display_name, message_id=message.id)
        
async def setup(bot: commands.Bot):
    await bot.add_cog(On_Message_Main_Cog(bot))