import asyncio
import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction, TextChannel, Embed
)

from firestores.fs_voice_log import FS_Voice_Log

from services.points.ui.embeds import Point_Panel_Embed
from services.points.ui.views import Point_Panel_View


FILENAME = "points_main_cog"

class Points_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_voice_log = FS_Voice_Log()

    @app_commands.command(name="vcログ確認", description="vcログの確認を行います。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(vc_id="VCのIDを入れてください。")
    async def vc_log_check_command(self, interaction: Interaction, vc_id: str):
        await interaction.response.send_message(content="情報取得中...", ephemeral=True)

        result = await self.fs_voice_log.fetch_vc_all(vc_id=vc_id)

        embed = Embed(
            title=f"『id: {vc_id}』の内訳",
            description=result,
        )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ポイントパネル", description="ポイント用のパネルを出力します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def point_panel_command(self, interaction: Interaction):
        await interaction.response.send_message(content="パネルを出力します。", ephemeral=True)

        embed = Point_Panel_Embed()
        view = Point_Panel_View()

        await interaction.channel.send(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Points_Main_Cog(bot))