import discord
from discord import (
    app_commands, Interaction, Embed,
    ButtonStyle, TextStyle,
    TextChannel, ForumChannel, Thread,
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
    Judging_Prof_Pass_Embed, Judging_Interview_Pass_Embed
)

from utils.emojis import *
from utils.colorcodes import *
from utils.ids import *
from utils.discord.role import resolve_role

from datetime import datetime
from zoneinfo import ZoneInfo

import re
import logging
import textwrap

FILENAME = "judging_views"
logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Asia/Tokyo")

LABEL_MAP = {
    "favorite": "おすすめ",
    "circle": "⭕️",
    "cross": "❌️",
    "caution": "注意",
}

class Judging_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Vote_Button(label="おすすめ", emoji=None, style=ButtonStyle.green, row=0, btn_type="FAVORITE"))
        self.add_item(Vote_Button(label="⭕️", emoji=None, style=ButtonStyle.blurple, row=0, btn_type="CIRCLE"))
        self.add_item(Vote_Button(label="❌️", emoji=None, style=ButtonStyle.gray, row=0, btn_type="CROSS"))
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
        match = re.search(r"(\d{15,25})", author_url or "")
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return
        target_id = int(match.group(1))

        try:
            target = interaction.guild.get_member(target_id) or await interaction.guild.fetch_member(target_id)
        except Exception as e:
            logger.error(f"Error while fetching member: {e}")
            await interaction.followup.send("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return 

        date_ymd = embed.footer.text

        before_cat = None
        for cat in ["favorite", "circle", "cross", "caution"]:
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
        match = re.search(r"(\d{15,25})", author_url or "")
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return
        target_id = int(match.group(1))
        
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
        self.add_item(Prof_Pass_Button(label="プロフ合格", emoji=DEFAULT.CIRCLE, style=ButtonStyle.blurple, row=1))
        self.add_item(Prof_Fail_Button(label="プロフ不合格", emoji=DEFAULT.CROSS, style=ButtonStyle.gray, row=1))

class Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_judging = FS_Judging()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        # 数字だけ抽出（Discord ID は 17〜19桁の数字）
        match = re.search(r"(\d{15,25})", author_url or "")
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return
        target_id = int(match.group(1))

        date_ymd = embed.footer.text

        data = await self.fs_judging.get_all_for_target_date(target_id=target_id, date_ymd=date_ymd)

        # ---- ここからEmbed生成 ----

        CATEGORY_INFO = {
            "favorite":   {"title": "おすすめ", "color": COLORS.BLUE},
            "circle": {"title": "⭕️", "color": COLORS.GREEN_LIGHT},
            "cross":    {"title": "❌️",     "color": COLORS.YELLOW},
            "caution":  {"title": "注意情報", "color": COLORS.RED},
        }

        # 全 message_id を縦断してカテゴリ別に集計する
        merged = {
            "favorite": [],
            "circle": [],
            "cross": [],
            "caution": [],
        }

        for msg_id, info in data.items():
            # 各カテゴリにデータを追加
            for cat in ("favorite", "circle", "cross", "caution"):
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

class Prof_Pass_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        # ---- 即 defer（Unknown interaction 対策）----
        try:
            await interaction.response.defer(thinking=True)
        except discord.NotFound:
            return

        # -------------------------
        # 対象ユーザーIDの取得
        # -------------------------
        if not interaction.message.embeds:
            await interaction.followup.send("プロフィール情報が見つかりません。", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        if not author_url:
            await interaction.followup.send("対象ユーザーの情報URLが見つかりません。", ephemeral=True)
            return

        match = re.search(r"(\d{15,25})", author_url or "")
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return
        target_id = int(match.group(1))
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        # ---- 安全に member を取得（Unknown Member 対策）----
        target = guild.get_member(target_id)
        if target is None:
            try:
                target = await guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send(
                    "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                    ephemeral=True,
                )
                return
            except discord.Forbidden:
                await interaction.followup.send(
                    "対象ユーザーの取得権限がありません。",
                    ephemeral=True,
                )
                return

        # -------------------------
        # ロール取得
        # -------------------------
        pm_role = guild.get_role(MAIN_ROLES.PROF_PASS)
        if pm_role is None:
            try:
                pm_role = await guild.fetch_role(MAIN_ROLES.PROF_PASS)
            except discord.NotFound:
                pm_role = None

        roles_to_add = [pm_role] if pm_role is not None else []
        if not roles_to_add:
            await interaction.followup.send("付与するロールが見つかりませんでした。", ephemeral=True)
            return

        # -------------------------
        # ロール付与
        # -------------------------
        try:
            await target.add_roles(*roles_to_add, reason="プロフ審査合格")
        except discord.Forbidden:
            await interaction.followup.send("ロール付与の権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"ロール付与に失敗しました: {e}", ephemeral=True)
            return

        # -------------------------
        # 結果表示
        # -------------------------
        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # プロフ審査合格

                https://discord.com/channels/1421436016442740749/1424994909370323056 に投稿があったら案内をお願いします。
                """
            ),
            color=COLORS.BLUE_LIGHTSKY,
        )
        result_embed.set_author(name=f"{target_id}")

        result_view = Interview_Panel_View()

        await interaction.followup.send(
            content=textwrap.dedent(
                f'''
                <@&{MAIN_ROLES.GUIDE}>
                面接官用テンプレ
                ```
                【当鯖を選んだ理由】
                【転生歴】
                【BAN歴】
                【主な活動時間】
                【年齢確認】
                【面白いについて】
                【面接官コメント】
                ```
                '''
            ),
            embed=result_embed,
            view=result_view
            )
        
        await interaction.message.edit(view=None)

        # -------------------------
        # Forum Thread のタグ変更
        # -------------------------
        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            before_tag_id = JUDGE_TAGS.NOW
            after_tag_id = JUDGE_TAGS.PROF_PASS

            # 現在のタグから before_tag だけ除外
            new_tags = [
                tag for tag in thread.applied_tags
                if tag.id != before_tag_id
            ]

            # after_tag がまだ無ければ追加
            if not any(tag.id == after_tag_id for tag in new_tags):
                forum = thread.parent
                if forum and isinstance(forum, discord.ForumChannel):
                    after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
                    if after_tag:
                        new_tags.append(after_tag)

            await thread.edit(applied_tags=new_tags)

        # -------------------------
        # 合格DM
        # -------------------------
        pass_embed = Judging_Prof_Pass_Embed()
        try:
            await target.send(embed=pass_embed)
        except Exception:
            date_tc_id = MAIN_CHANNELS.INTERVIEW_DATE

            date_tc = guild.get_channel(date_tc_id) or await guild.fetch_channel(date_tc_id)

            await date_tc.send(content=f"{target.mention}", embed=pass_embed)

class Prof_Fail_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        # ---- 即 defer（Unknown interaction 対策）----
        try:
            await interaction.response.defer(thinking=True)
        except discord.NotFound:
            return

        # -------------------------
        # 対象ユーザーIDの取得
        # -------------------------
        if not interaction.message.embeds:
            await interaction.followup.send("プロフィール情報が見つかりません。", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

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

        # ---- 安全に member を取得（Unknown Member 対策）----
        target = guild.get_member(target_id)
        if target is None:
            try:
                target = await guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send(
                    "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                    ephemeral=True,
                )
                return
            except discord.Forbidden:
                await interaction.followup.send(
                    "対象ユーザーの取得権限がありません。",
                    ephemeral=True,
                )
                return

        # -------------------------
        # キック処理
        # -------------------------
        try:
            await target.kick(reason="プロフ審査不合格のため")
        except discord.Forbidden:
            await interaction.followup.send("キック権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"キックに失敗しました: {e}", ephemeral=True)
            return

        # -------------------------
        # 結果表示
        # -------------------------
        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 不合格
                """
            ),
            color=COLORS.BLACK,
        )

        await interaction.followup.send(embed=result_embed)
        await interaction.message.edit(view=None)

        # -------------------------
        # Forum Thread のタグ変更
        #   NOW → FAIL
        # -------------------------
        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            before_tag_id = JUDGE_TAGS.NOW
            after_tag_id = JUDGE_TAGS.FAIL

            # 現在のタグから NOW だけ除外
            new_tags = [
                tag for tag in thread.applied_tags
                if tag.id != before_tag_id
            ]

            # FAIL タグが未付与なら追加
            if not any(tag.id == after_tag_id for tag in new_tags):
                forum = thread.parent
                if forum and isinstance(forum, discord.ForumChannel):
                    after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
                    if after_tag:
                        new_tags.append(after_tag)

            await thread.edit(applied_tags=new_tags, archived=True)

class Interview_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Interview_Pass_Button(label="面接合格", emoji=DEFAULT.CIRCLE, style=ButtonStyle.green, row=0))
        self.add_item(Interview_Fail_Button(label="面接不合格", emoji=DEFAULT.TRASH, style=ButtonStyle.red, row=0))

class Interview_Pass_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)

        embed = interaction.message.embeds[0]
        target_id = int(embed.author.name)

        guild = interaction.guild
        if guild is None:
            await interaction.edit_original_response(content="⚠️ ギルド情報が取得できません。", view=None)
            return

        # -------------------------
        # 対象メンバー取得
        # -------------------------
        try:
            target = guild.get_member(target_id) or await guild.fetch_member(target_id)
        except Exception:
            logger.error(f"Member Not Found: {target_id}")
            await interaction.edit_original_response(
                content="⚠️ このメンバーはサーバーから脱退しています。",
                view=None,
            )
            return

        # 付与/解除したいロールID（複数OK）
        ADD_ROLE_IDS = [
            MAIN_ROLES.SERVER_GUIDANCE,
            # MAIN_ROLES.XXXX,
        ]

        REMOVE_ROLE_IDS = [
            MAIN_ROLES.PROF_PASS,
            # MAIN_ROLES.XXXX,
        ]

        # -------------------------
        # ロール解決（複数）
        # -------------------------
        roles_to_add = []
        for rid in ADD_ROLE_IDS:
            role = await resolve_role(guild=guild, role_id=rid)
            if role is not None:
                roles_to_add.append(role)

        roles_to_remove = []
        for rid in REMOVE_ROLE_IDS:
            role = await resolve_role(guild=guild, role_id=rid)
            if role is not None:
                roles_to_remove.append(role)

        # 重複排除（念のため）
        roles_to_add = list({r.id: r for r in roles_to_add}.values())
        roles_to_remove = list({r.id: r for r in roles_to_remove}.values())

        # 「付与ロールが1つも無いなら止める」運用
        if not roles_to_add:
            await interaction.followup.send("付与するロールが見つかりませんでした。", ephemeral=True)
            return

        # -------------------------
        # ロール付与/削除（まとめて）
        # -------------------------
        try:
            # 既に持ってる/持ってないはDiscord側がよしなに処理してくれる（不要な変更は無視される）
            await target.add_roles(*roles_to_add, reason="面接合格")

            if roles_to_remove:
                await target.remove_roles(*roles_to_remove, reason="面接合格（旧ロール解除）")

        except discord.Forbidden:
            await interaction.followup.send("ロール編集の権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"ロール更新に失敗しました: {e}", ephemeral=True)
            return


        # -------------------------
        # 結果表示
        # -------------------------
        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 面接合格

                https://ptb.discord.com/channels/1421436016442740749/1451824654560923748 に投稿があったら案内をお願いします。

                説明開始ボタンで仮メンバーロールが付与
                説明完了ボタンで入口ロールを剥奪
                """
            ),
            color=COLORS.BLUE_LIGHTSKY,
        )
        result_embed.set_author(name=f"{target_id}")

        result_view = Server_Guidance_View()

        await interaction.followup.send(embed=result_embed, view=result_view)
        await interaction.message.edit(view=None)

        # -------------------------
        # Forum Thread のタグ変更
        # -------------------------
        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            before_tag_id = JUDGE_TAGS.PROF_PASS
            after_tag_id = JUDGE_TAGS.INT_PASS

            new_tags = [tag for tag in thread.applied_tags if tag.id != before_tag_id]

            if not any(tag.id == after_tag_id for tag in new_tags):
                forum = thread.parent
                if forum and isinstance(forum, ForumChannel):
                    after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
                    if after_tag:
                        new_tags.append(after_tag)

            await thread.edit(applied_tags=new_tags)

        # -------------------------
        # 合格DM
        # -------------------------
        pass_embed = Judging_Interview_Pass_Embed()
        try:
            await target.send(embed=pass_embed)
        except Exception:
            date_tc_id = MAIN_CHANNELS.SERVER_GUIDANCE
            date_tc = guild.get_channel(date_tc_id) or await guild.fetch_channel(date_tc_id)
            await date_tc.send(content=f"{target.mention}", embed=pass_embed)


class Interview_Fail_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)

        embed = interaction.message.embeds[0]
        target_id = int(embed.author.name)

        guild = interaction.guild

        # ---- 安全に member を取得（Unknown Member 対策）----
        target = guild.get_member(target_id)
        if target is None:
            try:
                target = await guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send(
                    "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                    ephemeral=True,
                )
                return
            except discord.Forbidden:
                await interaction.followup.send(
                    "対象ユーザーの取得権限がありません。",
                    ephemeral=True,
                )
                return

        # -------------------------
        # キック処理
        # -------------------------
        try:
            await target.kick(reason="面接不合格のため")
        except discord.Forbidden:
            await interaction.followup.send("キック権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"キックに失敗しました: {e}", ephemeral=True)
            return

        # -------------------------
        # 結果表示
        # -------------------------
        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 面接不合格
                """
            ),
            color=COLORS.BLACK,
        )

        await interaction.followup.send(embed=result_embed)
        await interaction.message.edit(view=None)

        # -------------------------
        # Forum Thread のタグ変更
        #   NOW → FAIL
        # -------------------------
        thread = interaction.channel
        if isinstance(thread, Thread):
            before_tag_id = JUDGE_TAGS.PROF_PASS
            after_tag_id = JUDGE_TAGS.FAIL

            # 現在のタグから NOW だけ除外
            new_tags = [
                tag for tag in thread.applied_tags
                if tag.id != before_tag_id
            ]

            # FAIL タグが未付与なら追加
            if not any(tag.id == after_tag_id for tag in new_tags):
                forum = thread.parent
                if forum and isinstance(forum, ForumChannel):
                    after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
                    if after_tag:
                        new_tags.append(after_tag)

            await thread.edit(applied_tags=new_tags, archived=True)
        
class Server_Guidance_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Guidance_Start_Button(label="説明開始", emoji=DEFAULT.NEXT, style=ButtonStyle.gray, row=0))
        self.add_item(Guidance_Pass_Button(label="説明完了", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=0))

class Guidance_Start_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row,
                         custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()

        if not interaction.message.embeds:
            await interaction.followup.send("対象Embedが見つかりません。", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        if not embed.author or not embed.author.name:
            await interaction.followup.send("対象ユーザーIDがEmbedにありません。", ephemeral=True)
            return

        target_id = int(embed.author.name)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド情報が取得できません。", ephemeral=True)
            return

        # ---- 安全に member を取得（Unknown Member 対策）----
        target = guild.get_member(target_id)
        if target is None:
            try:
                target = await guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send(
                    "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                    ephemeral=True,
                )
                return
            except discord.Forbidden:
                await interaction.followup.send(
                    "対象ユーザーの取得権限がありません。",
                    ephemeral=True,
                )
                return

        # 付与/解除したいロールID（複数OK）
        add_role_ids = [
            MAIN_ROLES.P_MEMBER,
        ]
        remove_role_ids = []

        role_ids_now = {r.id for r in target.roles}

        has_g_male = MAIN_ROLES.G_MALE in role_ids_now
        has_g_female = MAIN_ROLES.G_FEMALE in role_ids_now

        if has_g_male and not has_g_female:
            add_role_ids.append(MAIN_ROLES.P_MALE)
            remove_role_ids.append(MAIN_ROLES.G_MALE)
        elif has_g_female and not has_g_male:
            add_role_ids.append(MAIN_ROLES.P_FEMALE)
            remove_role_ids.append(MAIN_ROLES.G_FEMALE)
        else:
            await interaction.followup.send(
                "性別ロール（G_MALE/G_FEMALE）の判定ができませんでした。スタッフが確認してください。",
                ephemeral=True,
            )
            return

        # -------------------------
        # ロール解決（複数）
        # -------------------------
        roles_to_add = []
        for rid in add_role_ids:
            role = await resolve_role(guild=guild, role_id=rid)
            if role is not None:
                roles_to_add.append(role)

        roles_to_remove = []
        for rid in remove_role_ids:
            role = await resolve_role(guild=guild, role_id=rid)
            if role is not None:
                roles_to_remove.append(role)

        # 重複排除
        roles_to_add = list({r.id: r for r in roles_to_add}.values())
        roles_to_remove = list({r.id: r for r in roles_to_remove}.values())

        if not roles_to_add:
            await interaction.followup.send("付与するロールが見つかりませんでした。", ephemeral=True)
            return

        # 既に持ってる/持ってないで無駄打ちを減らす（任意だけどおすすめ）
        roles_to_add = [r for r in roles_to_add if r.id not in role_ids_now]
        roles_to_remove = [r for r in roles_to_remove if r.id in role_ids_now]

        # -------------------------
        # ロール付与/削除
        # -------------------------
        try:
            if roles_to_add:
                await target.add_roles(*roles_to_add, reason="案内開始（仮メンバー処理）")
            if roles_to_remove:
                await target.remove_roles(*roles_to_remove, reason="案内開始（入口男女解除）")
        except discord.Forbidden:
            await interaction.followup.send("ロール編集の権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"ロール更新に失敗しました: {e}", ephemeral=True)
            return

        await interaction.edit_original_response(content="仮メンバーロールを付与しました。")

class Guidance_Pass_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row,
                         custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()

        if not interaction.message.embeds:
            await interaction.followup.send("対象Embedが見つかりません。", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        if not embed.author or not embed.author.name:
            await interaction.followup.send("対象ユーザーIDがEmbedにありません。", ephemeral=True)
            return

        target_id = int(embed.author.name)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド情報が取得できません。", ephemeral=True)
            return

        # ---- 安全に member を取得（Unknown Member 対策）----
        target = guild.get_member(target_id)
        if target is None:
            try:
                target = await guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send(
                    "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                    ephemeral=True,
                )
                return
            except discord.Forbidden:
                await interaction.followup.send(
                    "対象ユーザーの取得権限がありません。",
                    ephemeral=True,
                )
                return

        remove_role_ids = [
            MAIN_ROLES.SERVER_GUIDANCE,
            MAIN_ROLES.PROF_PASS,
            MAIN_ROLES.GUEST,
        ]

        role_ids_now = {r.id for r in target.roles}

        # -------------------------
        # ロール解決（複数）
        # -------------------------
        roles_to_remove = []
        for rid in remove_role_ids:
            role = await resolve_role(guild=guild, role_id=rid)
            if role is not None:
                roles_to_remove.append(role)

        # 重複排除
        roles_to_remove = list({r.id: r for r in roles_to_remove}.values())

        # 既に持ってる/持ってないで無駄打ちを減らす（任意だけどおすすめ）
        roles_to_remove = [r for r in roles_to_remove if r.id in role_ids_now]

        # -------------------------
        # ロール付与/削除
        # -------------------------
        try:
            if roles_to_remove:
                await target.remove_roles(*roles_to_remove, reason="案内完了（入口ロール解除）")
        except discord.Forbidden:
            await interaction.followup.send("ロール編集の権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"ロール更新に失敗しました: {e}", ephemeral=True)
            return

        await interaction.edit_original_response(content="案内完了、入口ロールを外しました。", view=None)


        # -------------------------
        # Forum Thread のタグ変更
        #   INT_PASS → PASS
        # -------------------------
        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            before_tag_id = JUDGE_TAGS.INT_PASS
            after_tag_id = JUDGE_TAGS.PASS

            new_tags = [tag for tag in thread.applied_tags if tag.id != before_tag_id]

            if not any(tag.id == after_tag_id for tag in new_tags):
                forum = thread.parent
                if forum and isinstance(forum, discord.ForumChannel):
                    after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
                    if after_tag:
                        new_tags.append(after_tag)

            await thread.edit(applied_tags=new_tags, archived=True)

class Guide_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Guidance_Start_VC_Member_Button(label="VCメンバーに案内開始", emoji=DEFAULT.NEXT, style=ButtonStyle.gray, row=0))

class Guidance_Start_VC_Member_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("guild を取得できませんでした。", ephemeral=True)
            return

        # =========================
        # 対象VCの決定
        # =========================
        # 1) ボイスチャンネル上の操作なら interaction.channel が VC の可能性
        # 2) それ以外なら interaction.user の接続VC
        vc = None
        if isinstance(interaction.channel, discord.VoiceChannel):
            vc = interaction.channel
        else:
            if interaction.user.voice and interaction.user.voice.channel:
                if isinstance(interaction.user.voice.channel, discord.VoiceChannel):
                    vc = interaction.user.voice.channel

        if vc is None:
            await interaction.followup.send("対象VCが見つかりません（VC内で実行してください）。", ephemeral=True)
            return

        # =========================
        # 除外条件
        # =========================
        # 「このロールIDを持ってる人は除外」
        EXCLUDE_ROLE_IDS: set[int] = {
            MAIN_ROLES.GUIDE,
        }

        # ついでに bot 除外したいなら True
        EXCLUDE_BOTS = True

        # =========================
        # 付与/解除したいロールID（共通部分）
        # =========================
        BASE_ADD_ROLE_IDS = [
            MAIN_ROLES.P_MEMBER,
        ]
        BASE_REMOVE_ROLE_IDS: list[int] = []

        # =========================
        # 事前に Role を解決（キャッシュ/Fetch最小化）
        # =========================
        # 性別で分岐するので、使い得るロール全部をまとめて解決しておく
        all_possible_role_ids: set[int] = set(BASE_ADD_ROLE_IDS) | set(BASE_REMOVE_ROLE_IDS)
        all_possible_role_ids |= {
            MAIN_ROLES.P_MALE,
            MAIN_ROLES.P_FEMALE,
            MAIN_ROLES.G_MALE,
            MAIN_ROLES.G_FEMALE,
        }

        role_map: dict[int, discord.Role] = {}
        for rid in all_possible_role_ids:
            role = await resolve_role(guild=guild, role_id=rid)
            if role is not None:
                role_map[rid] = role

        # P_MEMBER が解決できないなら致命的
        if MAIN_ROLES.P_MEMBER not in role_map:
            await interaction.followup.send("付与するロール（P_MEMBER）が見つかりませんでした。", ephemeral=True)
            return

        # =========================
        # 対象メンバー収集（VC接続者）
        # =========================
        vc_members = list(vc.members)

        # 除外ロールを持つメンバーは対象外
        targets: list[discord.Member] = []
        excluded: list[discord.Member] = []

        for m in vc_members:
            if EXCLUDE_BOTS and m.bot:
                excluded.append(m)
                continue

            role_ids_now = {r.id for r in m.roles}
            if EXCLUDE_ROLE_IDS & role_ids_now:
                excluded.append(m)
                continue

            targets.append(m)

        if not targets:
            await interaction.followup.send(
                "対象ユーザーがいませんでした（除外条件により全員対象外の可能性）。",
                ephemeral=True,
            )
            return

        # =========================
        # 実行（各メンバーごとに性別判定して付与/解除）
        # =========================
        # 返却用
        granted_users_lines: list[str] = []
        failed_users_lines: list[str] = []
        used_role_ids: set[int] = set()  # 今回「使った」ロール一覧として返す用

        for member in targets:
            role_ids_now = {r.id for r in member.roles}

            has_g_male = MAIN_ROLES.G_MALE in role_ids_now
            has_g_female = MAIN_ROLES.G_FEMALE in role_ids_now

            add_role_ids = list(BASE_ADD_ROLE_IDS)
            remove_role_ids = list(BASE_REMOVE_ROLE_IDS)

            # 性別分岐
            if has_g_male and not has_g_female:
                add_role_ids.append(MAIN_ROLES.P_MALE)
                remove_role_ids.append(MAIN_ROLES.G_MALE)
            elif has_g_female and not has_g_male:
                add_role_ids.append(MAIN_ROLES.P_FEMALE)
                remove_role_ids.append(MAIN_ROLES.G_FEMALE)
            else:
                failed_users_lines.append(
                    f"- {member.mention}：性別ロール判定不可（G_MALE/G_FEMALE）"
                )
                continue

            # role_id -> Role 解決（事前に role_map 作ってるのでO(1)）
            roles_to_add = [role_map[rid] for rid in add_role_ids if rid in role_map]
            roles_to_remove = [role_map[rid] for rid in remove_role_ids if rid in role_map]

            # 無駄打ち削減
            roles_to_add = [r for r in roles_to_add if r.id not in role_ids_now]
            roles_to_remove = [r for r in roles_to_remove if r.id in role_ids_now]

            if not roles_to_add and not roles_to_remove:
                # 何も変わらないならスキップ（ログ目的なら書いてもOK）
                granted_users_lines.append(f"- {member.mention}：変更なし")
                continue

            try:
                if roles_to_add:
                    await member.add_roles(*roles_to_add, reason="案内開始（VC接続メンバー一括）")
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="案内開始（入口男女解除）")

                # 返却用ログ
                add_names = [r.name for r in roles_to_add] or ["(なし)"]
                remove_names = [r.name for r in roles_to_remove] or ["(なし)"]
                granted_users_lines.append(
                    f"- {member.mention}：付与 {', '.join(add_names)} / 解除 {', '.join(remove_names)}"
                )

                used_role_ids |= {r.id for r in roles_to_add}
                used_role_ids |= {r.id for r in roles_to_remove}

            except discord.Forbidden:
                failed_users_lines.append(f"- {member.mention}：権限不足（Forbidden）")
            except Exception as e:
                failed_users_lines.append(f"- {member.mention}：失敗 {type(e).__name__}: {e}")

        # =========================
        # 結果返却（Embed）
        # =========================
        used_roles = [role_map[rid].mention for rid in used_role_ids if rid in role_map]
        if not used_roles:
            # 変更なし or 全員失敗の可能性
            used_roles = ["(なし)"]

        # 長文対策：フィールドは1024文字制限があるので切る
        def _chunk_lines(lines: list[str], limit: int = 900) -> str:
            s = "\n".join(lines)
            if len(s) <= limit:
                return s
            # ざっくり切る（厳密にやるなら行単位で詰める）
            return s[:limit] + "\n...(省略)"

        embed = discord.Embed(
            title="✅ 案内開始：VC接続メンバー処理結果",
            description=f"対象VC：{vc.mention}\n対象人数：{len(targets)}（除外：{len(excluded)}）",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="付与/解除で使用したロール一覧",
            value="\n".join(used_roles),
            inline=False,
        )
        embed.add_field(
            name="付与されたユーザー一覧",
            value=_chunk_lines(granted_users_lines) if granted_users_lines else "(なし)",
            inline=False,
        )
        if failed_users_lines:
            embed.add_field(
                name="失敗/スキップ（要確認）",
                value=_chunk_lines(failed_users_lines),
                inline=False,
            )

        await interaction.edit_original_response(content=None, embed=embed, view=None)