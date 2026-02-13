import asyncio
import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction, TextChannel
)

from services.voice_channel.embeds import QM_Create_Panel
from services.voice_channel.views import VC_Create_QM_Panel_View

from utils.ids import MAIN_CHANNELS

import logging

FILENAME = "vc_create_main_cog"

class VC_Create_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="vc作成パネル", description="vc作成用パネルを出力します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(
        vc_type=[
            app_commands.Choice(name="qm", value="qm"),
        ]
    )
    async def vc_create_panel(self, interaction: Interaction, vc_type: app_commands.Choice[str]):
        await interaction.response.send_message(content="パネルを出力中...", ephemeral=True)

        type_map = {
            "qm": (QM_Create_Panel(), VC_Create_QM_Panel_View())
        }

        embed, view = type_map.get(vc_type.value)

        await interaction.channel.send(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(VC_Create_Main_Cog(bot))