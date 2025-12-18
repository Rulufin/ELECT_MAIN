import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import Guild, Message, Thread, ForumChannel

from utils.ids import *
from services.judging.embeds import Judging_Profile_Embed, Judging_Entry_Embed
from services.judging.views import Judging_Panel_View, Judging_Result_View
from firestores.fs_judging import FS_Judging

logger = logging.getLogger(__name__)

FILENAME = "on_reaction_judging"
TIMEZONE = ZoneInfo("Asia/Tokyo")


class OnReactionJudging:
    """
    プロフ審査リアクション時の処理を担当するクラス。

    外からは下の `on_reaction_judging(guild, message)` を呼ぶだけでOK。
    """

    def __init__(self) -> None:
        self.fs_judging = FS_Judging()

    async def handle(self, guild: Guild, message: Message) -> None:
        author = message.author

        # -----------------------------
        # チャンネル / スレッド取得
        # -----------------------------
        # 審査結果用 ForumChannel
        judge_forum: ForumChannel = (
            guild.get_channel(MAIN_CHANNELS.PROFILE_JUDGE_RESULT)
            or await guild.fetch_channel(MAIN_CHANNELS.PROFILE_JUDGE_RESULT)
        )

        if not isinstance(judge_forum, ForumChannel):
            logger.error(
                f"[{FILENAME}] PROFILE_JUDGE_RESULT is not ForumChannel (id={MAIN_CHANNELS.PROFILE_JUDGE_RESULT})"
            )
            return

        # 元メッセージの作成日時 → JST → yyyymmdd
        created_at_utc = message.created_at  # discordは基本UTC
        created_at_jst = created_at_utc.astimezone(TIMEZONE)
        formatted_date = created_at_jst.strftime("%Y%m%d")

        # -----------------------------
        # 審査用メッセージを審査チャンネルに送信
        # -----------------------------
        embed = Judging_Profile_Embed(author=author, message=message, formatted_date=formatted_date)
        panel_view = Judging_Panel_View()

        judge_ch = (
            guild.get_channel(MAIN_CHANNELS.PROFILE_JUDGE)
            or await guild.fetch_channel(MAIN_CHANNELS.PROFILE_JUDGE)
        )

        judge_message = await judge_ch.send(
            content=f"<@&{MAIN_ROLES.MEMBER}>",  # ロールメンション想定
            embed=embed,
            view=panel_view,
        )

        # -----------------------------
        # 結果表示用スレッドを Forum に作成
        # -----------------------------
        result_view = Judging_Result_View()

        # スレッド名: "ユーザーID-YYYYMMDD"
        thread_name = f"{author.id}-{formatted_date}"

        tag_obj = judge_forum.get_tag(JUDGE_TAGS.NOW)

        applied_tags = []
        if tag_obj is not None:
            applied_tags.append(tag_obj)
        else:
            # タグが見つからなかったときのログだけ出す
            logger.warning(
                f"[{FILENAME}] ForumTag NOW (id={JUDGE_TAGS.NOW}) not found on forum {judge_forum.id}"
            )

        created = await judge_forum.create_thread(
            name=thread_name,
            embed=embed,
            view=result_view,
            applied_tags=applied_tags,
        )

        # discord.py のバージョンによっては Thread / ThreadWithMessage のどちらかが返る
        if isinstance(created, discord.Thread):
            thread = created
            starter_message = None
        else:
            # ThreadWithMessage 的なオブジェクトを想定
            thread = created.thread
            starter_message = created.message  # 必要なら使える

        # ここから先は thread を使えばOK
        await self.fs_judging.init_day_entry(
            target_id=author.id,
            message_id=judge_message.id,
            date_ymd=formatted_date,
            thread_id=thread.id,
        )

        # -----------------------------
        # ユーザーDMに「審査開始メッセージ」を送信
        # -----------------------------
        try:
            await author.send(embed=Judging_Entry_Embed())
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"[{FILENAME}] Judging message not sent to {author}: DM not received. Exception: {str(e)}",
                    exc_info=True,
                )
            return


# ======================================================
# 外から使う用の「関数ラッパ」
# ======================================================

# モジュールロード時に1インスタンスだけ持つ
_judging_handler = OnReactionJudging()


async def on_reaction_judging(guild: Guild, message: Message) -> None:
    """
    raw_reaction側からはこの関数を呼べばOK。

    例:
        from on_event.on_reactions.judging import on_reaction_judging
        await on_reaction_judging(guild=guild, message=message)
    """
    await _judging_handler.handle(guild, message)
