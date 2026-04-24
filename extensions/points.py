import asyncio
import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction, TextChannel, Embed
)

from datetime import datetime
from zoneinfo import ZoneInfo

from firestores.fs_voice_log import FS_Voice_Log
from firestores.fs_points import FS_Points

from services.points.ui.embeds import Point_Panel_Embed
from services.points.ui.views import Point_Panel_View
from services.points.enums import Points_Type, Genre_Type

from utils.discord_helpers.user_ids import coerce_user_ids, coerce_user_ids_or_raw_id

FILENAME = "points_main_cog"
TIMEZONE = ZoneInfo("Asia/Tokyo")

class Points_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_voice_log = FS_Voice_Log()
        self.fs_points = FS_Points()

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

    @app_commands.command(name="add-point", description="ポイントを付与します")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        対象ユーザー="ユーザーID/メンションで指定してください。",
        ポイント数="付与したいポイント数を指定してください(マイナス値も可)"
    )
    async def add_point_command(self, interaction: Interaction, 対象ユーザー: str, ポイント数: int):
        await interaction.response.defer(ephemeral=True)

        user_ids = coerce_user_ids_or_raw_id(対象ユーザー)
        if not user_ids:
            await interaction.followup.send("対象ユーザーを取得できませんでした。", ephemeral=True)
            return

        now = datetime.now(TIMEZONE)
        note = "手動付与" if ポイント数 >= 0 else "手動減算"

        for user_id in user_ids:
            await self.fs_points.record_event(
                user_id=user_id,
                event_type=Points_Type.ADJUST,
                genre=Genre_Type.ADMIN,
                delta=ポイント数,
                note=note,
                ts=now,
            )

        await interaction.followup.send(
            f"{len(user_ids)}人に {ポイント数:+,} pt を反映しました。",
            ephemeral=True,
        )

    @app_commands.command(name="check-userlists", description="各ユーザーの所持ポイントをランキングで出します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def check_Userlists(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        rows = await self.fs_points.list_all_user_totals(
            limit=5000,
            order_desc=True,
            include_zero=True,
        )

        if not rows:
            await interaction.followup.send("ポイントデータが見つかりませんでした。", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Guild情報を取得できませんでした。", ephemeral=True)
            return

        lines: list[str] = []

        for index, row in enumerate(rows, start=1):
            user_id = int(row["user_id"])
            points = int(row.get("total_points", 0) or 0)

            member = guild.get_member(user_id)
            user_name = member.display_name if member else f"Unknown User"

            line = f"{index:02d}. {user_name}(<@{user_id}>) {points} points"
            lines.append(line)

        embeds: list[Embed] = []
        current_lines: list[str] = []
        current_len = 0

        # Discord Embed description 上限は 4096 文字
        # 念のため少し余裕を持たせる
        max_desc_len = 3800

        for line in lines:
            add_len = len(line) + 1  # +改行分

            if current_lines and current_len + add_len > max_desc_len:
                embed = Embed(
                    title="ユーザーポイントランキング",
                    description="\n".join(current_lines),
                    color=discord.Color.blue(),
                )
                embeds.append(embed)
                current_lines = [line]
                current_len = add_len
            else:
                current_lines.append(line)
                current_len += add_len

        if current_lines:
            embed = Embed(
                title="ユーザーポイントランキング",
                description="\n".join(current_lines),
                color=discord.Color.blue(),
            )
            embeds.append(embed)

        # defer(ephemeral=True) しているので followup で分割送信
        # 1通目
        await interaction.followup.send(embed=embeds[0], ephemeral=True)

        # 2通目以降
        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Points_Main_Cog(bot))