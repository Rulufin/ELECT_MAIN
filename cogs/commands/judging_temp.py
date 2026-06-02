import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import re

import discord
from discord.ext import commands
from discord import app_commands, Interaction, Message

from services.judging.temp.service import TempJudgingService

from firestores.fs_judging_temp import FS_Judging_Temp

from utils.discord.helpers.resolve import (
    resolve_member_from_value,
    resolve_forum_channel,
    resolve_text_channel,
)
from utils.ids import MAIN_CHANNELS

logger = logging.getLogger(__name__)
FILENAME = "judging_temp_main_cog"

TIMEZONE = ZoneInfo("Asia/Tokyo")


def resolve_date_ymd_from_legacy_message(legacy_message: Message) -> str | None:
    if legacy_message.embeds:
        embed = legacy_message.embeds[0]
        footer = getattr(embed, "footer", None)
        footer_text = getattr(footer, "text", None)

        if footer_text:
            match = re.search(r"(20\d{6})", footer_text)
            if match:
                return match.group(1)

    created_at = getattr(legacy_message, "created_at", None)
    if created_at is not None:
        return created_at.astimezone(TIMEZONE).strftime("%Y%m%d")

    return None


class JT_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.service = TempJudgingService()
        self.fs_judging_temp = FS_Judging_Temp()

    @app_commands.command(name="仮免審査設定")
    @app_commands.guild_only()
    @app_commands.describe(対象ユーザー="ユーザーID/メンションを入力")
    async def callback(self, interaction: Interaction, 対象ユーザー: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド内でのみ実行できます。", ephemeral=True)
            return

        member = await resolve_member_from_value(guild, 対象ユーザー)
        if member is None:
            await interaction.followup.send("対象ユーザーを取得できませんでした。", ephemeral=True)
            return

        user_forum = await resolve_forum_channel(guild, MAIN_CHANNELS.TEMP_JUDGE_USER_FORUM)
        if user_forum is None:
            await interaction.followup.send(
                "メンバー用仮免審査フォーラムを取得できませんでした。",
                ephemeral=True,
            )
            return

        admin_forum = await resolve_forum_channel(guild, MAIN_CHANNELS.TEMP_JUDGE_ADMIN_FORUM)
        if admin_forum is None:
            await interaction.followup.send(
                "管理用仮免審査フォーラムを取得できませんでした。",
                ephemeral=True,
            )
            return

        try:
            await self.service.create_temp_judge_panel(
                guild=guild,
                member=member,
                user_forum=user_forum,
                admin_forum=admin_forum,
            )
        except Exception as e:
            logger.exception("[%s] create_temp_judge_panel failed", FILENAME)
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await interaction.followup.send(
            f"{member.mention} の仮免審査を作成しました。",
            ephemeral=True,
        )

    @app_commands.command(name="仮免審査移行")
    @app_commands.guild_only()
    @app_commands.describe(
        message_id="移行したい旧TextChannel上のメッセージID。未指定なら一括移行。",
        件数="一括移行時の最大件数。未指定なら全件。",
    )
    async def migrate_temp_judge(
        self,
        interaction: Interaction,
        message_id: str | None = None,
        件数: int | None = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド内でのみ実行できます。", ephemeral=True)
            return

        legacy_text_channel = await resolve_text_channel(guild, MAIN_CHANNELS.TEMP_JUDGE)
        if legacy_text_channel is None:
            await interaction.followup.send(
                "旧ユーザー用仮免審査テキストチャンネルを取得できませんでした。",
                ephemeral=True,
            )
            return

        user_forum = await resolve_forum_channel(guild, MAIN_CHANNELS.TEMP_JUDGE_USER_FORUM)
        if user_forum is None:
            await interaction.followup.send(
                "新しいユーザー用仮免審査フォーラムを取得できませんでした。",
                ephemeral=True,
            )
            return

        result_map = {
            "migrated": "移行しました。",
            "already_migrated": "すでに移行済みです。",
            "entry_not_found": "対応するFirestoreデータが見つかりませんでした。",
            "embed_not_found": "対象メッセージにEmbedがありません。",
            "author_url_not_found": "Embedのauthor.urlが見つかりません。",
            "date_ymd_not_found": "日付を取得できませんでした。",
            "target_id_not_found": "対象ユーザーIDを抽出できませんでした。",
            "user_message_not_found": "新Forum側の開始メッセージ取得に失敗しました。",
            "same_message_id": "message_id が同一のため移行不要でした。",
            "not_found": "旧Firestoreエントリが見つかりませんでした。",
            "error_occurred": "移行中にエラーが発生しました。",
        }

        if message_id is not None:
            try:
                target_message_id = int(message_id)
            except ValueError:
                await interaction.followup.send("message_id は数値で指定してください。", ephemeral=True)
                return

            try:
                legacy_message = await legacy_text_channel.fetch_message(target_message_id)
            except discord.NotFound:
                await interaction.followup.send("指定メッセージが見つかりませんでした。", ephemeral=True)
                return
            except discord.Forbidden:
                await interaction.followup.send("メッセージ取得権限がありません。", ephemeral=True)
                return
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"メッセージ取得に失敗しました: {e}",
                    ephemeral=True,
                )
                return

            date_ymd = resolve_date_ymd_from_legacy_message(legacy_message)
            if date_ymd is None:
                await interaction.followup.send(
                    f"message_id={target_message_id}\n結果: {result_map['date_ymd_not_found']}",
                    ephemeral=True,
                )
                return

            try:
                result = await self.service.migrate_legacy_user_panel(
                    guild=guild,
                    legacy_message=legacy_message,
                    user_forum=user_forum,
                    date_ymd=date_ymd,
                )
            except Exception:
                logger.exception("[%s] single migrate failed message_id=%s", FILENAME, target_message_id)
                await interaction.followup.send(
                    "移行中にエラーが発生しました。",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                f"message_id={target_message_id}\n"
                f"date_ymd={date_ymd}\n"
                f"結果: {result_map.get(result, result)}",
                ephemeral=True,
            )
            return

        migrated = 0
        already_migrated = 0
        entry_not_found = 0
        embed_not_found = 0
        author_url_not_found = 0
        date_ymd_not_found = 0
        target_id_not_found = 0
        user_message_not_found = 0
        same_message_id = 0
        error_occurred = 0
        other = 0

        processed = 0

        try:
            async for legacy_message in legacy_text_channel.history(limit=件数, oldest_first=True):
                processed += 1

                date_ymd = resolve_date_ymd_from_legacy_message(legacy_message)
                if date_ymd is None:
                    date_ymd_not_found += 1
                    continue

                try:
                    result = await self.service.migrate_legacy_user_panel(
                        guild=guild,
                        legacy_message=legacy_message,
                        user_forum=user_forum,
                        date_ymd=date_ymd,
                    )
                except Exception:
                    logger.exception(
                        "[%s] bulk migrate failed message_id=%s",
                        FILENAME,
                        legacy_message.id,
                    )
                    error_occurred += 1
                    continue

                if result == "migrated":
                    migrated += 1
                elif result == "already_migrated":
                    already_migrated += 1
                elif result == "entry_not_found":
                    entry_not_found += 1
                elif result == "embed_not_found":
                    embed_not_found += 1
                elif result == "author_url_not_found":
                    author_url_not_found += 1
                elif result == "date_ymd_not_found":
                    date_ymd_not_found += 1
                elif result == "target_id_not_found":
                    target_id_not_found += 1
                elif result == "user_message_not_found":
                    user_message_not_found += 1
                elif result == "same_message_id":
                    same_message_id += 1
                elif result == "error_occurred":
                    error_occurred += 1
                else:
                    other += 1

        except Exception:
            logger.exception("[%s] bulk migrate failed", FILENAME)
            await interaction.followup.send(
                "一括移行中にエラーが発生しました。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="仮免審査移行結果",
            description="\n".join([
                "仮免審査一括移行結果",
                f"processed: {processed}",
                f"migrated: {migrated}",
                f"already_migrated: {already_migrated}",
                f"entry_not_found: {entry_not_found}",
                f"embed_not_found: {embed_not_found}",
                f"author_url_not_found: {author_url_not_found}",
                f"date_ymd_not_found: {date_ymd_not_found}",
                f"target_id_not_found: {target_id_not_found}",
                f"user_message_not_found: {user_message_not_found}",
                f"same_message_id: {same_message_id}",
                f"error_occurred: {error_occurred}",
                f"other: {other}",
            ]),
            color=discord.Color.green(),
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="仮免審査none修復")
    @app_commands.guild_only()
    @app_commands.describe(
        message_id="修復したい旧TextChannel上のメッセージID。未指定なら一括修復。",
        件数="一括修復時の最大件数。未指定なら全件。",
    )
    async def repair_temp_judge_none(
        self,
        interaction: Interaction,
        message_id: str | None = None,
        件数: int | None = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド内でのみ実行できます。", ephemeral=True)
            return

        legacy_text_channel = await resolve_text_channel(guild, MAIN_CHANNELS.TEMP_JUDGE)
        if legacy_text_channel is None:
            await interaction.followup.send(
                "旧ユーザー用仮免審査テキストチャンネルを取得できませんでした。",
                ephemeral=True,
            )
            return

        result_map = {
            "migrated": "None から正しい date_ymd へ修復しました。",
            "already_repaired": "すでに修復済みです。",
            "not_found": "None 側のFirestoreデータが見つかりませんでした。",
            "embed_not_found": "対象メッセージにEmbedがありません。",
            "author_url_not_found": "Embedのauthor.urlが見つかりません。",
            "target_id_not_found": "対象ユーザーIDを抽出できませんでした。",
            "date_ymd_not_found": "日付を取得できませんでした。",
            "invalid_date_ymd": "補正先 date_ymd が不正です。",
            "error_occurred": "修復中にエラーが発生しました。",
        }

        if message_id is not None:
            try:
                target_message_id = int(message_id)
            except ValueError:
                await interaction.followup.send("message_id は数値で指定してください。", ephemeral=True)
                return

            try:
                legacy_message = await legacy_text_channel.fetch_message(target_message_id)
            except discord.NotFound:
                await interaction.followup.send("指定メッセージが見つかりませんでした。", ephemeral=True)
                return
            except discord.Forbidden:
                await interaction.followup.send("メッセージ取得権限がありません。", ephemeral=True)
                return
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"メッセージ取得に失敗しました: {e}",
                    ephemeral=True,
                )
                return

            try:
                result = await self.service.repair_none_date_from_legacy_message(
                    legacy_message=legacy_message,
                    delete_old=True,
                )
            except Exception:
                logger.exception("[%s] single none-repair failed message_id=%s", FILENAME, target_message_id)
                await interaction.followup.send(
                    "修復中にエラーが発生しました。",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                f"message_id={target_message_id}\n結果: {result_map.get(result, result)}",
                ephemeral=True,
            )
            return

        try:
            results = await self.service.repair_none_date_entries_in_text_channel(
                guild=guild,
                legacy_text_channel=legacy_text_channel,
                limit=件数,
                only_bot_messages=True,
            )
        except Exception:
            logger.exception("[%s] bulk none-repair failed", FILENAME)
            await interaction.followup.send(
                "一括修復中にエラーが発生しました。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="仮免審査 None 修復結果",
            description="\n".join([
                "仮免審査 None 修復結果",
                f"migrated: {results.get('migrated', 0)}",
                f"already_repaired: {results.get('already_repaired', 0)}",
                f"not_found: {results.get('not_found', 0)}",
                f"embed_not_found: {results.get('embed_not_found', 0)}",
                f"author_url_not_found: {results.get('author_url_not_found', 0)}",
                f"target_id_not_found: {results.get('target_id_not_found', 0)}",
                f"date_ymd_not_found: {results.get('date_ymd_not_found', 0)}",
                f"invalid_date_ymd: {results.get('invalid_date_ymd', 0)}",
                f"error_occurred: {results.get('error_occurred', 0)}",
                f"other: {results.get('other', 0)}",
            ]),
            color=discord.Color.blurple(),
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="仮免審査パネル修正", description="footer_textの修正用")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(message_id="修正対象メッセージID")
    async def panel_edit(
        self,
        interaction: Interaction,
        message_id: str
    ):
        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel

        if channel is None:
            await interaction.followup.send(
                "チャンネルを取得できませんでした。",
                ephemeral=True
            )
            return

        try:
            message = await channel.fetch_message(int(message_id))
        except Exception:
            await interaction.followup.send(
                "メッセージ取得に失敗しました。",
                ephemeral=True
            )
            return

        if not message.embeds:
            await interaction.followup.send(
                "Embedが存在しません。",
                ephemeral=True
            )
            return

        embed = message.embeds[0]

        footer = getattr(embed, "footer", None)
        footer_text = getattr(footer, "text", None)

        created_at = message.created_at
        date_ymd = created_at.astimezone(TIMEZONE).strftime("%Y%m%d")

        new_embed = embed.copy()

        if footer_text:
            new_footer = f"{footer_text} | {date_ymd}"
        else:
            new_footer = date_ymd

        new_embed.set_footer(text=new_footer)

        await message.edit(embed=new_embed)

        await interaction.followup.send(
            "footerを修正しました。",
            ephemeral=True
        )

    @app_commands.command(name="仮免審査パネル再作成", description="ユーザー側仮免審査パネルを再作成します")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user_id="対象ユーザーID",
        message_id="Firestore上で現在紐づいている旧message_id",
    )
    async def recreate_temp_judge_panel(
        self,
        interaction: Interaction,
        user_id: str,
        message_id: str,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド内でのみ実行できます。", ephemeral=True)
            return

        try:
            target_id = int(user_id)
            old_message_id = int(message_id)
        except ValueError:
            await interaction.followup.send(
                "user_id と message_id は数値で指定してください。",
                ephemeral=True,
            )
            return

        user_forum = await resolve_forum_channel(guild, MAIN_CHANNELS.TEMP_JUDGE_USER_FORUM)
        if user_forum is None:
            await interaction.followup.send(
                "メンバー用仮免審査フォーラムを取得できませんでした。",
                ephemeral=True,
            )
            return

        result_map = {
            "migrated": "ユーザー側仮免審査パネルを再作成しました。",
            "entry_not_found": "対応するFirestoreデータが見つかりませんでした。",
            "date_ymd_not_found": "date_ymd を取得できませんでした。",
            "member_not_found": "対象メンバーを取得できませんでした。",
            "profile_channel_not_found": "プロフィール用チャンネルを特定できませんでした。",
            "profile_message_not_found": "プロフィールメッセージを取得できませんでした。",
            "user_message_not_found": "新しい開始メッセージの取得に失敗しました。",
            "same_message_id": "message_id が同一のため更新不要でした。",
            "not_found": "旧Firestoreエントリが見つかりませんでした。",
            "error_occurred": "再作成中にエラーが発生しました。",
        }

        try:
            result = await self.service.recreate_user_panel_from_firestore(
                guild=guild,
                target_id=target_id,
                old_message_id=old_message_id,
                user_forum=user_forum,
                archive_old_thread=False,
            )
        except Exception:
            logger.exception(
                "[%s] recreate_temp_judge_panel failed target_id=%s old_message_id=%s",
                FILENAME,
                target_id,
                old_message_id,
            )
            await interaction.followup.send(
                "再作成中にエラーが発生しました。",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"user_id={target_id}\nmessage_id={old_message_id}\n結果: {result_map.get(result, result)}",
            ephemeral=True,
        )

    @app_commands.command(
        name="仮免審査データ修復",
        description="指定ユーザーの仮免審査Firestoreデータを、最新message_idへ統合して修復します。"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        対象ユーザー="修復したい対象ユーザーのDiscord ID"
    )
    async def repair_judging_temp(
        self,
        interaction: Interaction,
        対象ユーザー: str,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            target_id = int(str(対象ユーザー).strip())
        except Exception:
            await interaction.followup.send(
                "対象ユーザーIDは数値で指定してください。",
                ephemeral=True,
            )
            return

        try:
            result = await self.fs_judging_temp.unify_target_keep_latest_message(
                target_id=target_id,
                delete_old=True,
            )

            status = result.get("status")

            if status == "not_found":
                await interaction.followup.send(
                    f"対象ユーザー `{target_id}` のデータは見つかりませんでした。",
                    ephemeral=True,
                )
                return

            if status == "no_valid_date_doc":
                await interaction.followup.send(
                    "\n".join(
                        [
                            f"対象ユーザー `{target_id}` のデータは見つかりましたが、",
                            "`date_ymd != None` の正規ドキュメントが存在しないため修復できませんでした。",
                            f"scanned_docs: {result.get('scanned_docs', 0)}",
                        ]
                    ),
                    ephemeral=True,
                )
                return

            if status != "ok":
                await interaction.followup.send(
                    "\n".join(
                        [
                            "修復中にエラーが発生しました。",
                            f"target_id: {target_id}",
                            f"status: {status}",
                        ]
                    ),
                    ephemeral=True,
                )
                return

            lines = [
                "仮免審査データの修復が完了しました。",
                f"target_id: {result.get('target_id')}",
                f"採用message_id: {result.get('target_message_id')}",
                f"採用date_ymd: {result.get('target_date_ymd')}",
                f"admin_thread_id: {result.get('admin_thread_id')}",
                f"user_thread_id: {result.get('user_thread_id')}",
                f"user_message_id: {result.get('user_message_id')}",
                f"circle_count: {result.get('circle_count', 0)}",
                f"cross_count: {result.get('cross_count', 0)}",
                f"caution_count: {result.get('caution_count', 0)}",
                f"scanned_docs: {result.get('scanned_docs', 0)}",
                f"deleted_docs: {result.get('deleted_docs', 0)}",
            ]

            await interaction.followup.send(
                "\n".join(lines),
                ephemeral=True,
            )

        except Exception as e:
            logger.exception(
                "[%s] repair_judging_temp failed target_id=%s error=%s",
                FILENAME,
                対象ユーザー,
                e,
            )
            await interaction.followup.send(
                "修復処理中に例外が発生しました。ログを確認してください。",
                ephemeral=True,
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(JT_Main_Cog(bot))