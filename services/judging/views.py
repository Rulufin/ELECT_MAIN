import discord
from discord import (
    app_commands, Interaction, Embed,
    ButtonStyle, TextStyle,
)
from discord.ui import (
    View, Button, Modal, 
    TextInput
)

from firestores.fs_judging import FS_Judging

from services.judging.embeds import (
    Judging_Result_Embed, Judging_Result_Change_Embed, Judging_Result_Clear_Embed,
    Judging_Caution_Embed,
    Judging_Profile_Embed,
    Judging_Pass_Embed
)

from utils.emojis import *
from utils.colorcodes import *
from utils.ids import *

from datetime import datetime
from zoneinfo import ZoneInfo

import re
import logging
import textwrap

FILENAME = "judging_views"
logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Asia/Tokyo")

LABEL_MAP = {
    "circle": "おすすめ",
    "triangle": "おまかせ",
    "cross": "NG",
    "caution": "注意",
}

class Judging_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Vote_Button(label="おすすめ", emoji=None, style=ButtonStyle.green, row=0, btn_type="CIRCLE"))
        self.add_item(Vote_Button(label="おまかせ", emoji=None, style=ButtonStyle.blurple, row=0, btn_type="TRIANGLE"))
        self.add_item(Vote_Button(label="NG", emoji=None, style=ButtonStyle.gray, row=0, btn_type="CROSS"))
        self.add_item(Caution_Button(label="注意情報", emoji=None, style=ButtonStyle.red, row=1, btn_type="CAUTION"))


class Vote_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}")
        self.btn_type = btn_type
        self.fs_judging = FS_Judging()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        # 数字だけ抽出（Discord ID は 17〜19桁の数字）
        match = re.search(r"(\d{15,25})", author_url)
        target_id = int(match.group(1) if match else None)

        try:
            target = interaction.guild.get_member(target_id) or await interaction.guild.fetch_member(target_id)
        except Exception as e:
            logger.error(f"Error while fetching member: {e}")
            await interaction.followup.send("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return 

        date_ymd = embed.footer.text

        before_cat = None
        for cat in ["circle", "triangle", "cross", "caution"]:
            cat_map = await self.fs_judging.get_category(
                target_id=target_id,
                message_id=interaction.message.id,
                date_ymd=date_ymd,
                category=cat,
            )
            for item in cat_map.values():
                if item.get("user_id") == str(interaction.user.id):
                    before_cat = cat
                    break
            if before_cat:
                break

        before_label = LABEL_MAP.get(before_cat)  # ← 日本語化

        # --- 投票実行 ---
        result = await self.fs_judging.set_vote(
            category=self.btn_type,
            target_id=target_id,
            message_id=interaction.message.id,
            date_ymd=date_ymd,
            user=interaction.user,
            comment=None,
        )

        # --- embed 作成 ---
        if result == "add":
            embed = Judging_Result_Embed(label=self.label, target=target)

        elif result == "change":
            embed = Judging_Result_Change_Embed(
                before=before_label,   # ← 日本語ラベルに！
                label=self.label,
                target=target,
            )

        elif result == "remove":
            embed = Judging_Result_Clear_Embed(target=target)

        elif result == "no_change":
            embed = Embed(description="変更はありません。")

        await interaction.followup.send(embed=embed, ephemeral=True)


class Caution_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}")
        self.btn_type = btn_type
        self.fs_judging = FS_Judging()

    async def callback(self, interaction: Interaction):
        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        # 数字だけ抽出（Discord ID は 17〜19桁の数字）
        match = re.search(r"(\d{15,25})", author_url)
        target_id = int(match.group(1) if match else None)
        
        date_ymd = embed.footer.text

        # Caution_Modal に必要な情報を渡してモーダルを表示
        # 前回のコメントを取得してから表示
        previous_comment = await self._get_previous_comment(target_id, interaction.message.id, date_ymd)

        modal = Caution_Modal(self.btn_type, target_id, date_ymd, previous_comment)

        await interaction.response.send_modal(modal)

    async def _get_previous_comment(self, target_id, message_id, date_ymd):
        # Firestore から対象メンバーの前回のコメントを取得する処理
        try:
            caution_data = await self.fs_judging.get_category(
                target_id=target_id,
                message_id=message_id,
                date_ymd=date_ymd,
                category="caution")
            
            # 前回のコメントがあれば、それを返す。無ければNone。
            if target_id in caution_data:
                return caution_data[target_id].get("comment", None)
            return None
        except Exception as e:
            logger.error(f"Error while fetching previous caution comment: {e}")
            return None


class Caution_Modal(Modal):
    def __init__(self, btn_type, target_id, date_ymd, previous_comment=None):
        super().__init__(title="注意情報記載", timeout=None)

        # 取得するための変数
        self.btn_type = btn_type
        self.target_id = target_id
        self.date_ymd = date_ymd
        self.fs_judging = FS_Judging()

        # 前回のコメントをデフォルト値にセット
        self.comment_input = TextInput(
            label="理由",
            style=TextStyle.paragraph,
            placeholder=textwrap.dedent(
                '''
                注意情報を記載してください。
                いただいた情報は管理内でしか共有されません。
                '''
            ),
            required=True,
            max_length=800,
            default=previous_comment if previous_comment else ""  # もしコメントがあれば表示
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            target = interaction.guild.get_member(self.target_id) or await interaction.guild.fetch_member(self.target_id)
        except Exception as e:
            logger.error(f"Error while fetching member during caution submission: {e}")
            await interaction.followup.send("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return 

        # 投票の結果を保存
        result = await self.fs_judging.set_vote(
            category=self.btn_type,
            target_id=self.target_id,
            message_id=interaction.message.id,
            date_ymd=self.date_ymd,
            user=interaction.user,
            comment=self.comment_input.value,
        )

        if result == "error_occurred":
            await interaction.followup.send("入力できませんでした。再度お試しください。", ephemeral=True)
            return

        # 新しいEmbedを作成して送信
        embed = Judging_Caution_Embed(
            before=self.comment_input.default,  # 前回のコメント
            after=self.comment_input.value,  # 新しいコメント
            target=target
        )

        # 結果を送信
        await interaction.followup.send(embed=embed, ephemeral=True)

class Judging_Result_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Check_Button(label="確認", emoji=DEFAULT.EYES, style=ButtonStyle.green, row=0))
        self.add_item(Pass_Button(label="合格-男性", emoji=DEFAULT.CIRCLE, style=ButtonStyle.blurple, row=1, btn_type="MALE"))
        self.add_item(Pass_Button(label="合格-女性", emoji=DEFAULT.CIRCLE, style=ButtonStyle.red, row=1, btn_type="FEMALE"))
        self.add_item(Fail_Button(label="不合格", emoji=DEFAULT.CROSS, style=ButtonStyle.gray, row=2))

class Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_judging = FS_Judging()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        # 数字だけ抽出（Discord ID は 17〜19桁の数字）
        match = re.search(r"(\d{15,25})", author_url)
        target_id = int(match.group(1) if match else None)

        date_ymd = embed.footer.text

        data = await self.fs_judging.get_all_for_target_date(target_id=target_id, date_ymd=date_ymd)

        # ---- ここからEmbed生成 ----

        CATEGORY_INFO = {
            "circle":   {"title": "おすすめ", "color": COLORS.BLUE},
            "triangle": {"title": "おまかせ", "color": COLORS.GREEN_LIGHT},
            "cross":    {"title": "NG",     "color": COLORS.YELLOW},
            "caution":  {"title": "注意情報", "color": COLORS.RED},
        }

        # 全 message_id を縦断してカテゴリ別に集計する
        merged = {
            "circle": [],
            "triangle": [],
            "cross": [],
            "caution": [],
        }

        for msg_id, info in data.items():
            # 各カテゴリにデータを追加
            for cat in ("circle", "triangle", "cross", "caution"):
                for idx, entry in sorted(info.get(cat, {}).items(), key=lambda x: int(x[0])):
                    if cat == "caution":
                        merged[cat].append(
                            f"{idx}. {entry['user_name']} (<@{entry['user_id']}>)\n　{entry.get('comment','')}"
                        )
                    else:
                        merged[cat].append(
                            f"{idx}. {entry['user_name']} (<@{entry['user_id']}>)"
                        )

        # ---- Embed分割生成 ----
        embeds: list[discord.Embed] = []

        for cat, entries in merged.items():
            if not entries:
                continue  # 空カテゴリはスキップ

            title = CATEGORY_INFO[cat]["title"]
            color = CATEGORY_INFO[cat]["color"]

            # 4096文字制限に配慮
            page_text = ""
            page_num = 1

            for line in entries:
                # 1ページが長くなりすぎたら新しいEmbed
                if len(page_text) + len(line) + 2 > 4000:
                    embed = discord.Embed(
                        title=f"{title} ({page_num})",
                        description=page_text,
                        color=color,
                    )
                    embeds.append(embed)
                    page_text = ""
                    page_num += 1

                page_text += line + "\n"

            # 最後のページを追加
            if page_text:
                embed = discord.Embed(
                    title=f"{title} ({page_num})",
                    description=page_text,
                    color=color,
                )
                embeds.append(embed)

        # ---- 送信 ----
        if not embeds:
            await interaction.followup.send("データがありません。", ephemeral=True)
            return

        for emb in embeds:
            await interaction.followup.send(embed=emb)

class Pass_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type: str):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}",
        )
        self.btn_type = btn_type

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        # --- 対象ユーザーの取得 ---
        if not interaction.message.embeds:
            await interaction.followup.send("プロフィール情報が見つかりません。", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        author_url = getattr(embed.author, "url", None)

        if not author_url:
            await interaction.followup.send("対象ユーザーの情報URLが見つかりません。", ephemeral=True)
            return

        match = re.search(r"(\d{15,25})", author_url)
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target_id = int(match.group(1))
        guild = interaction.guild

        if guild is None:
            await interaction.followup.send("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        target = guild.get_member(target_id) or await guild.fetch_member(target_id)

        # --- ロール取得 ---
        if self.btn_type == "MALE":
            gender_role_id = MAIN_ROLES.MALE
        else:
            gender_role_id = MAIN_ROLES.FEMALE

        gender_role = guild.get_role(gender_role_id)
        if gender_role is None:
            gender_role = await guild.fetch_role(gender_role_id)

        pm_role = guild.get_role(MAIN_ROLES.MEMBER_P)
        if pm_role is None:
            pm_role = await guild.fetch_role(MAIN_ROLES.MEMBER_P)

        # 念のため None チェック
        roles_to_add = [r for r in (gender_role, pm_role) if r is not None]
        if not roles_to_add:
            await interaction.followup.send("付与するロールが見つかりませんでした。", ephemeral=True)
            return

        # --- ロール付与 ---
        try:
            await target.add_roles(*roles_to_add, reason="入場審査合格")
        except Exception as e:
            await interaction.followup.send(f"ロール付与に失敗しました: {e}", ephemeral=True)
            return

        # --- 結果表示 ---
        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 合格
                """
            ),
            color=COLORS.BLUE_LIGHTSKY,
        )

        await interaction.followup.send(embed=result_embed)
        await interaction.message.edit(view=None)

        # --- 合格DM ---
        pass_embed = Judging_Pass_Embed()
        try:
            await target.send(embed=pass_embed)
        except Exception:
            await interaction.followup.send(content="合格者にDMを送信できませんでした。", ephemeral=True)


class Fail_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        # --- 対象ユーザー取得 ---
        if not interaction.message.embeds:
            await interaction.followup.send("プロフィール情報が見つかりません。", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        author_url = getattr(embed.author, "url", None)

        if not author_url:
            await interaction.followup.send("対象ユーザーの情報URLが見つかりません。", ephemeral=True)
            return

        match = re.search(r"(\d{15,25})", author_url)
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target_id = int(match.group(1))
        guild = interaction.guild

        if guild is None:
            await interaction.followup.send("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        target = guild.get_member(target_id) or await guild.fetch_member(target_id)

        # --- キック ---
        try:
            await target.kick(reason="入場審査不合格のため")
        except Exception as e:
            await interaction.followup.send(f"キックに失敗しました: {e}", ephemeral=True)
            return

        # --- 結果表示 ---
        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 不合格
                """
            )
        )

        await interaction.followup.send(embed=result_embed)
        await interaction.message.edit(view=None)
