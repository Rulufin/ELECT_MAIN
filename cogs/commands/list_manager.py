import asyncio
import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction, TextChannel
)

from services.list_manager.ui.embeds import Blacklist_Manage_Embed
from services.list_manager.ui.views import Blacklist_Manage_View

from utils.ids import MAIN_CHANNELS

import logging

FILENAME = "list_manager_main_cog"

class List_Manager_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ブラックリスト管理", description="ブラックリストの追加削除などを行うパネルを出力します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def list_manager_panel(self, interaction: Interaction):
        await interaction.response.send_message(content="パネルを出力します。", ephemeral=True)
        
        embed = Blacklist_Manage_Embed()
        view = Blacklist_Manage_View()

        await interaction.channel.send(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(List_Manager_Main_Cog(bot))