import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction, Embed
)

from services.judging.embeds import Judging_Guide_Panel_Embed
from services.judging.views import Judging_Panel_View, Judging_Result_View, Server_Guidance_View, Guide_Panel_View

from utils.colorcodes import COLORS

import textwrap
import logging

logger = logging.getLogger(__name__)

FILENAME = "judging_extensions"

class Judging_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="プロフ審査パネル修正", description="指定メッセージのパネルを編集します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(m_id = "メッセージIDを入力")
    async def prof_judge_panel_remake(self, interaction: Interaction, m_id: str):
        await interaction.response.defer(ephemeral=True)

        ch = interaction.channel
        m = await ch.fetch_message(int(m_id))

        await m.edit(view=Judging_Panel_View())

        await interaction.followup.send(content=f"パネルを修正しました。\n{m.jump_url}", ephemeral=True)

    @app_commands.command(name="審査内容パネル修正", description="指定メッセージのパネルを編集します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(m_id = "メッセージIDを入力")
    async def judge_info_panel_remake(self, interaction: Interaction, m_id: str):
        await interaction.response.defer(ephemeral=True)

        ch = interaction.channel
        m = await ch.fetch_message(int(m_id))

        await m.edit(view=Judging_Result_View())

        await interaction.followup.send(content=f"パネルを修正しました。\n{m.jump_url}", ephemeral=True)

    @app_commands.command(name="サーバー案内パネル修正", description="指定メッセージのパネルを編集します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(m_id = "メッセージIDを入力")
    async def guidance_panel_remake(self, interaction: Interaction, m_id: str, t_id: str):
        await interaction.response.defer(ephemeral=True)

        ch = interaction.channel
        m = await ch.fetch_message(int(m_id))

        g = interaction.guild
        t = g.get_member(int(t_id)) or await g.fetch_member(int(t_id))

        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {t.display_name} ({t.mention})
                # 面接合格

                https://ptb.discord.com/channels/1421436016442740749/1451824654560923748 に投稿があったら案内をお願いします。

                説明開始ボタンで仮メンバーロールが付与
                説明完了ボタンで入口ロールを剥奪
                """
            ),
            color=COLORS.BLUE_LIGHTSKY,
        )
        result_embed.set_author(name=f"{t_id}")

        await m.edit(embed=result_embed, view=Server_Guidance_View())

        await interaction.followup.send(content=f"パネルを修正しました。\n{m.jump_url}", ephemeral=True)

    @app_commands.command(name="案内人用パネル", description="案内任用のパネルを表示します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def guide_panel_create(self, interaction: Interaction):
        await interaction.response.send_message(content="パネルを投稿します。", ephemeral=True)

        embed = Judging_Guide_Panel_Embed()
        view = Guide_Panel_View()

        await interaction.channel.send(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Judging_Main_Cog(bot))