import logging

import discord
from discord import Guild, Member, Message, TextChannel
from discord.ext import commands

from services.judging.profile.service import ProfileJudgingService

from utils.discord_helpers.resolve import (
    resolve_guild,
    resolve_member,
    resolve_message,
    resolve_text_channel,
)
from utils.discord_helpers.check import (
    has_any_role
)
from utils.ids import *

logger = logging.getLogger(__name__)

FILENAME = "on_reaction_main"

ADMINISTRATOR_IDS = [
    MAIN_ROLES.ADMINISTRATOR_ONE,
    MAIN_ROLES.ADMINISTRATOR_TWO,
]


class On_Reaction_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.profile_judge_service = ProfileJudgingService()

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self,
        payload: discord.RawReactionActionEvent,
    ) -> None:

        guild: Guild | None = await resolve_guild(self.bot, payload.guild_id)
        if guild is None:
            # DM などギルド外はスキップ
            return

        member: Member | None = await resolve_member(
            guild,
            payload.user_id,
            allow_bot=False,
        )
        if member is None:
            return

        # ADMINISTRATOR_IDS のロールを持っているか
        if not has_any_role(member, ADMINISTRATOR_IDS):
            return

        channel_id = payload.channel_id
        if channel_id != MAIN_CHANNELS.PROFILE_PROVISIONAL:
            return

        channel: TextChannel | None = await resolve_text_channel(guild, channel_id)
        if channel is None:
            return

        message: Message | None = await resolve_message(channel, payload.message_id)
        if message is None:
            return

        await self.profile_judge_service.start_from_reaction(
            guild=guild,
            message=message,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(On_Reaction_Main_Cog(bot))