from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands, Interaction
from discord.ext import commands

from firestores.fs_rank import FS_Rank
from services.rank_system.elect_rank_image import ElectRankCardImager, ElectRankCardData
from utils.discord.helpers.user_ids import coerce_user_ids_or_raw_id

logger = logging.getLogger(__name__)

FILENAME = "rank_cog"

_imager = ElectRankCardImager()


async def _resolve_user(interaction: Interaction, user_id: int) -> Optional[discord.abc.User]:
    """ギルドメンバーを優先し、見つからなければグローバルユーザーをフェッチする。"""
    if interaction.guild:
        member = interaction.guild.get_member(user_id)
        if member:
            return member
    try:
        return await interaction.client.fetch_user(user_id)
    except discord.NotFound:
        return None


class Rank_Cog(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.fs_rank = FS_Rank()

    # ──────────────────────────────────────────────────────────────
    # /rank
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(name="rank", description="ランクカードを表示します。")
    @app_commands.guild_only()
    @app_commands.describe(対象ユーザー="確認したいユーザー（メンションまたはID、省略時は自分）")
    async def rank_command(
        self,
        interaction: Interaction,
        user: Optional[str] = None,
    ) -> None:
        await interaction.response.defer()

        if user is None:
            target: discord.abc.User = interaction.user
        else:
            ids = coerce_user_ids_or_raw_id(user)
            if not ids:
                await interaction.followup.send(
                    "ユーザーを特定できませんでした。メンションかIDを指定してください。",
                    ephemeral=True,
                )
                return
            resolved = await _resolve_user(interaction, next(iter(ids)))
            if resolved is None:
                await interaction.followup.send(
                    "指定されたユーザーが見つかりませんでした。",
                    ephemeral=True,
                )
                return
            target = resolved

        state = await self.fs_rank.get_state(target.id)
        tc_points = state.total_tc if state else 0
        vc_points = state.total_vc if state else 0

        file = await _imager.build(
            user=target,
            data=ElectRankCardData(tc_points=tc_points, vc_points=vc_points),
        )
        await interaction.followup.send(file=file)

    # ──────────────────────────────────────────────────────────────
    # /rank-set  (管理者専用)
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(name="rank-set", description="ユーザーのランクポイントを直接設定します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="設定するユーザー（メンションまたはID）",
        text="TCポイント（省略時は変更なし）",
        voice="VCポイント（省略時は変更なし）",
    )
    async def rank_set_command(
        self,
        interaction: Interaction,
        user: str,
        text: Optional[int] = None,
        voice: Optional[int] = None,
    ) -> None:
        if text is None and voice is None:
            await interaction.response.send_message(
                "text か voice を少なくとも1つ指定してください。", ephemeral=True
            )
            return

        ids = coerce_user_ids_or_raw_id(user)
        if not ids:
            await interaction.response.send_message(
                "ユーザーを特定できませんでした。メンションかIDを指定してください。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        user_id = next(iter(ids))
        await self.fs_rank.set_points(user_id, total_tc=text, total_vc=voice)

        parts = []
        if text is not None:
            parts.append(f"TC: **{text:,}** pt")
        if voice is not None:
            parts.append(f"VC: **{voice:,}** pt")

        await interaction.followup.send(
            f"<@{user_id}> のランクポイントを設定しました。\n" + " / ".join(parts),
            ephemeral=True,
        )

    # ──────────────────────────────────────────────────────────────
    # /rank-add  (管理者専用)
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(name="rank-add", description="ユーザーのランクポイントを加算します。")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="加算するユーザー（メンションまたはID）",
        text="加算するTCポイント（省略時は変更なし）",
        voice="加算するVCポイント（省略時は変更なし）",
    )
    async def rank_add_command(
        self,
        interaction: Interaction,
        user: str,
        text: Optional[int] = None,
        voice: Optional[int] = None,
    ) -> None:
        if text is None and voice is None:
            await interaction.response.send_message(
                "text か voice を少なくとも1つ指定してください。", ephemeral=True
            )
            return

        ids = coerce_user_ids_or_raw_id(user)
        if not ids:
            await interaction.response.send_message(
                "ユーザーを特定できませんでした。メンションかIDを指定してください。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        user_id = next(iter(ids))

        if text is not None:
            await self.fs_rank.add_tc_points(user_id, text)
        if voice is not None:
            await self.fs_rank.add_vc_points(user_id, voice)

        parts = []
        if text is not None:
            parts.append(f"TC: **+{text:,}** pt")
        if voice is not None:
            parts.append(f"VC: **+{voice:,}** pt")

        await interaction.followup.send(
            f"<@{user_id}> のランクポイントを加算しました。\n" + " / ".join(parts),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Rank_Cog(bot))
