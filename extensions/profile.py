import asyncio
import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction, TextChannel
)

from firestores.fs_user_info import FS_Profile
from utils.ids import MAIN_CHANNELS

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

FILENAME = "profile_extensions"


class Profile_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.fs_profile = FS_Profile()

    # ----------------------------------------------------
    # /プロフィール一括保存
    # ----------------------------------------------------
    @app_commands.command(
        name="プロフィール一括保存",
        description="プロフィールチャンネルのメッセージを全件Firestoreに保存します。"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def profile_all_save(self, interaction: Interaction):
        await interaction.response.send_message(
            content="プロフィール保存処理を開始しました。",
            ephemeral=True
        )

        guild = interaction.guild

        male_ch: TextChannel = guild.get_channel(MAIN_CHANNELS.PROFILE_MALE)
        female_ch: TextChannel = guild.get_channel(MAIN_CHANNELS.PROFILE_FEMALE)

        if male_ch is None or female_ch is None:
            await interaction.followup.send(
                "プロフィールチャンネルが取得できませんでした。",
                ephemeral=True
            )
            return

        target_channels = [male_ch, female_ch]

        total_saved = 0
        chunk_saved = 0       # チャンク内で何件保存したか
        CHUNK_SIZE = 50       # ここを変えれば「何件ごとに休むか」を調整可能
        SLEEP_SEC = 1.5       # 休憩時間（秒）

        for ch in target_channels:
            logger.info(f"[プロフィール保存] チャンネル読み込み開始: {ch.id}")

            # 古いメッセージから順に処理したい場合は oldest_first=True
            async for message in ch.history(limit=None, oldest_first=True):
                author = message.author

                # botは除外
                if author.bot:
                    continue

                try:
                    await self.fs_profile.add_profile_data(
                        author_id=str(author.id),
                        author_name=author.display_name,
                        message_id=str(message.id)
                    )
                    total_saved += 1
                    chunk_saved += 1

                except Exception as e:
                    logger.error(
                        f"[Firestore保存エラー] {e} (ChannelID: {ch.id}, MessageID: {message.id})"
                    )

                # 50件ごとに少し待つ
                if chunk_saved >= CHUNK_SIZE:
                    logger.info(
                        f"[プロフィール保存] {CHUNK_SIZE}件処理完了、レートリミット対策で {SLEEP_SEC} 秒待機します。"
                    )
                    chunk_saved = 0
                    await asyncio.sleep(SLEEP_SEC)

        await interaction.followup.send(
            f"プロフィールを **{total_saved} 件** 保存しました。",
            ephemeral=True
        )

    # ----------------------------------------------------
    # /プロフィール保存
    # ----------------------------------------------------
    @app_commands.command(
        name="プロフィール保存",
        description="プロフィールURLからデータの保存を行います。"
    )
    @app_commands.guild_only()
    @app_commands.describe(url="プロフィールのURLを入れてください。")
    async def profile_url_save(self, interaction: Interaction, url: str):
        await interaction.response.send_message(
            content="プロフィール保存処理を開始しました。",
            ephemeral=True
        )

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "ギルド内でのみ使用できます。",
                ephemeral=True
            )
            return

        # ---- URLパース ----
        try:
            parsed = urlparse(url)
            # /channels/<guild_id>/<channel_id>/<message_id>
            parts = parsed.path.split("/")
            # ['', 'channels', guild_id, ch_id, msg_id] みたいな形を想定
            if len(parts) < 5 or parts[1] != "channels":
                raise ValueError("URL形式不正")

            guild_id_str = parts[2]
            channel_id_str = parts[3]
            message_id_str = parts[4]

            channel_id = int(channel_id_str)
            message_id = int(message_id_str)

        except Exception:
            await interaction.followup.send(
                "メッセージURLの形式が正しくありません。",
                ephemeral=True
            )
            return

        # 他ギルドのURLが貼られていた場合
        try:
            if int(guild_id_str) != guild.id:
                await interaction.followup.send(
                    "このサーバーのメッセージURLではありません。",
                    ephemeral=True
                )
                return
        except Exception:
            # guild_id_str が数値じゃないなど
            await interaction.followup.send(
                "メッセージURLの解析に失敗しました。",
                ephemeral=True
            )
            return

        # ---- チャンネル取得 ----
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except discord.NotFound:
                await interaction.followup.send(
                    "指定されたチャンネルが見つかりませんでした。",
                    ephemeral=True
                )
                return
            except discord.Forbidden:
                await interaction.followup.send(
                    "指定されたチャンネルへのアクセス権がありません。",
                    ephemeral=True
                )
                return
            except Exception as e:
                logger.exception("チャンネル取得中にエラー: %s", e)
                await interaction.followup.send(
                    "チャンネル取得中にエラーが発生しました。",
                    ephemeral=True
                )
                return

        # プロフィール用チャンネル以外なら弾く
        if channel.id not in (MAIN_CHANNELS.PROFILE_MALE, MAIN_CHANNELS.PROFILE_FEMALE):
            await interaction.followup.send(
                "このURLはプロフィールチャンネルのメッセージではありません。",
                ephemeral=True
            )
            return

        # ---- メッセージ取得 ----
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            await interaction.followup.send(
                "指定されたメッセージが見つかりませんでした。",
                ephemeral=True
            )
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "メッセージ取得の権限がありません。",
                ephemeral=True
            )
            return
        except Exception as e:
            logger.exception("メッセージ取得中にエラー: %s", e)
            await interaction.followup.send(
                "メッセージ取得中にエラーが発生しました。",
                ephemeral=True
            )
            return

        author = message.author

        # もしbotプロフィールは保存しないならここで弾く
        if author.bot:
            await interaction.followup.send(
                "Botユーザーのプロフィールは保存対象外です。",
                ephemeral=True
            )
            return

        # ---- Firestore保存 ----
        try:
            await self.fs_profile.add_profile_data(
                author_id=str(author.id),
                author_name=author.display_name,
                message_id=str(message.id),
            )
        except Exception as e:
            logger.exception("Firestore保存中にエラー: %s", e)
            await interaction.followup.send(
                "プロフィール保存中にエラーが発生しました。",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"プロフィールを保存しました。\n"
            f"- ユーザー: {author.mention}\n"
            f"- メッセージID: `{message.id}`",
            ephemeral=True
        )

# ----------------------------------------------------
# setup
# ----------------------------------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(Profile_Main_Cog(bot))
