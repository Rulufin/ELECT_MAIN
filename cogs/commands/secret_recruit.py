import asyncio
import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction, TextChannel
)

from services.recruit.ui.embeds import Recruit_Panel_Embed, Recruit_Check_Embed
from services.recruit.ui.views import Recruit_Panel_View, Recruit_Check_View

from utils.ids import MAIN_CHANNELS

import logging

FILENAME = "secret_rcruit_main_cog"

class Secret_Recruit_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="裏募集作成確認", description="裏募集作成用、確認用パネルを出力します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def secret_recruit_create_panel(self, interaction: Interaction):
        await interaction.response.send_message(content="パネルを出力中...", ephemeral=True)

        create_embed = Recruit_Panel_Embed()
        create_view = Recruit_Panel_View()

        await interaction.channel.send(embed=create_embed, view=create_view)

        check_embed = Recruit_Check_Embed()
        check_view = Recruit_Check_View()

        await interaction.channel.send(embed=check_embed, view=check_view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Secret_Recruit_Main_Cog(bot))