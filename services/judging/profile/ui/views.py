import logging
import textwrap
from typing import Optional

import discord
from discord import (
    Interaction,
    Embed,
    ButtonStyle,
    TextStyle,
    ForumChannel,
    Thread,
)
from discord.ui import View, Button, Modal, TextInput

from firestores.fs_judging import FS_Judging

from services.judging.profile.ui.embeds import (
    Judging_Result_Embed,
    Judging_Result_Change_Embed,
    Judging_Result_Clear_Embed,
    Judging_Caution_Embed,
    Judging_Prof_Pass_Embed,
    Judging_Interview_Pass_Embed,
)
from services.judging.temp.service import TempJudgingService
from services.judging.helper.embed import extract_date_ymd, build_action_confirm_embed
from services.judging.helper.text import chunk_lines

from utils.emojis import *
from utils.colorcodes import *
from utils.ids import *
from utils.discord.helpers.resolve import (
    resolve_role,
    resolve_target_member,
    resolve_channel,
    resolve_message,
)
from utils.discord.helpers.check import has_any_role
from utils.discord.helpers.embed import (
    get_first_embed_from_message,
    extract_user_id_from_author_name,
    extract_user_id_from_author_url,
)
from utils.discord.helpers.thread import switch_thread_tag

FILENAME = "judging_views"
logger = logging.getLogger(__name__)

LABEL_MAP = {
    "favorite": "おすすめ",
    "circle": "⭕️",
    "cross": "❌️",
    "caution": "注意",
}


# =========================================================
# Confirm View
# =========================================================

class Judging_Action_Confirm_View(View):
    def __init__(
        self,
        *,
        action_type: str,
        target_id: int,
        source_channel_id: int,
        source_message_id: int,
    ):
        super().__init__(timeout=180)
        self.add_item(
            Judging_Action_Ok_Button(
                action_type=action_type,
                target_id=target_id,
                source_channel_id=source_channel_id,
                source_message_id=source_message_id,
            )
        )
        self.add_item(Judging_Action_Cancel_Button())


class Judging_Action_Ok_Button(Button):
    def __init__(
        self,
        *,
        action_type: str,
        target_id: int,
        source_channel_id: int,
        source_message_id: int,
    ):
        super().__init__(
            label="OK",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.green,
            row=0,
            custom_id=(
                f"{FILENAME}_{action_type}_{self.__class__.__name__}_"
                f"{target_id}_{source_message_id}"
            ),
        )
        self.action_type = action_type
        self.target_id = target_id
        self.source_channel_id = source_channel_id
        self.source_message_id = source_message_id

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)

        guild = interaction.guild
        if guild is None:
            await interaction.edit_original_response(
                content="ギルド情報を取得できませんでした。",
                embed=None,
                view=None,
            )
            return

        target = await resolve_target_member(guild, self.target_id)
        if target is None:
            await interaction.edit_original_response(
                content="対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                embed=None,
                view=None,
            )
            return

        source_channel = await resolve_channel(guild, self.source_channel_id)
        source_message = await resolve_message(source_channel, self.source_message_id)

        try:
            if self.action_type == "prof_pass":
                await self._run_prof_pass(
                    interaction=interaction,
                    guild=guild,
                    target=target,
                    source_message=source_message,
                    source_channel=source_channel,
                )

            elif self.action_type == "prof_fail":
                await self._run_prof_fail(
                    interaction=interaction,
                    target=target,
                    source_message=source_message,
                    source_channel=source_channel,
                )

            elif self.action_type == "interview_pass":
                await self._run_interview_pass(
                    interaction=interaction,
                    guild=guild,
                    target=target,
                    source_message=source_message,
                    source_channel=source_channel,
                )

            elif self.action_type == "interview_fail":
                await self._run_interview_fail(
                    interaction=interaction,
                    target=target,
                    source_message=source_message,
                    source_channel=source_channel,
                )

            else:
                await interaction.edit_original_response(
                    content="不明な操作です。",
                    embed=None,
                    view=None,
                )

        except Exception as e:
            logger.exception("[%s] confirm action failed: %s", FILENAME, self.action_type)
            await interaction.edit_original_response(
                content=f"処理に失敗しました: {e}",
                embed=None,
                view=None,
            )

    async def _clear_source_view(
        self,
        source_message: Optional[discord.Message],
    ) -> None:
        if source_message is None:
            return

        try:
            await source_message.edit(view=None)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning("[%s] failed to clear source view", FILENAME)

    async def _run_prof_pass(
        self,
        *,
        interaction: Interaction,
        guild: discord.Guild,
        target: discord.Member,
        source_message: Optional[discord.Message],
        source_channel: Optional[discord.abc.GuildChannel | Thread],
    ):
        pm_role = await resolve_role(guild=guild, role_id=MAIN_ROLES.PROF_PASS)
        roles_to_add = [pm_role] if pm_role is not None else []

        if not roles_to_add:
            await interaction.edit_original_response(
                content="付与するロールが見つかりませんでした。",
                embed=None,
                view=None,
            )
            return

        try:
            await target.add_roles(*roles_to_add, reason="プロフ審査合格")
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="ロール付与の権限がありません。",
                embed=None,
                view=None,
            )
            return

        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # プロフ審査合格

                https://discord.com/channels/1421436016442740749/1424994909370323056 に投稿があったら案内をお願いします。
                """
            ).strip(),
            color=COLORS.BLUE_LIGHTSKY,
        )
        result_embed.set_author(name=f"{target.id}")

        result_view = Interview_Panel_View()

        await interaction.edit_original_response(
            content=textwrap.dedent(
                f"""
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
                """
            ).strip(),
            embed=result_embed,
            view=result_view,
        )

        await self._clear_source_view(source_message)

        await switch_thread_tag(
            thread=source_channel if isinstance(source_channel, Thread) else None,
            before_tag_id=JUDGE_TAGS.NOW,
            after_tag_id=JUDGE_TAGS.PROF_PASS,
            archived=False,
        )

        pass_embed = Judging_Prof_Pass_Embed()
        try:
            await target.send(embed=pass_embed)
        except Exception:
            date_tc_id = MAIN_CHANNELS.INTERVIEW_DATE
            date_tc = guild.get_channel(date_tc_id) or await guild.fetch_channel(date_tc_id)
            await date_tc.send(content=f"{target.mention}", embed=pass_embed)

    async def _run_prof_fail(
        self,
        *,
        interaction: Interaction,
        target: discord.Member,
        source_message: Optional[discord.Message],
        source_channel: Optional[discord.abc.GuildChannel | Thread],
    ):
        try:
            await target.kick(reason="プロフ審査不合格のため")
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="キック権限がありません。",
                embed=None,
                view=None,
            )
            return

        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 不合格
                """
            ).strip(),
            color=COLORS.BLACK,
        )

        await interaction.edit_original_response(
            content=None,
            embed=result_embed,
            view=None,
        )

        await self._clear_source_view(source_message)

        await switch_thread_tag(
            thread=source_channel if isinstance(source_channel, Thread) else None,
            before_tag_id=JUDGE_TAGS.NOW,
            after_tag_id=JUDGE_TAGS.FAIL,
            archived=True,
        )

    async def _run_interview_pass(
        self,
        *,
        interaction: Interaction,
        guild: discord.Guild,
        target: discord.Member,
        source_message: Optional[discord.Message],
        source_channel: Optional[discord.abc.GuildChannel | Thread],
    ):
        add_role_ids = [
            MAIN_ROLES.SERVER_GUIDANCE,
        ]
        remove_role_ids = [
            MAIN_ROLES.PROF_PASS,
        ]

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

        roles_to_add = list({r.id: r for r in roles_to_add}.values())
        roles_to_remove = list({r.id: r for r in roles_to_remove}.values())

        if not roles_to_add:
            await interaction.edit_original_response(
                content="付与するロールが見つかりませんでした。",
                embed=None,
                view=None,
            )
            return

        try:
            await target.add_roles(*roles_to_add, reason="面接合格")
            if roles_to_remove:
                await target.remove_roles(*roles_to_remove, reason="面接合格（旧ロール解除）")
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="ロール編集の権限がありません。",
                embed=None,
                view=None,
            )
            return

        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 面接合格

                https://ptb.discord.com/channels/1421436016442740749/1451824654560923748 に投稿があったら案内をお願いします。

                説明開始ボタンで仮メンバーロールが付与
                説明完了ボタンで入口ロールを剥奪
                """
            ).strip(),
            color=COLORS.BLUE_LIGHTSKY,
        )
        result_embed.set_author(name=f"{target.id}")

        result_view = Server_Guidance_View()

        await interaction.edit_original_response(
            content=None,
            embed=result_embed,
            view=result_view,
        )

        await self._clear_source_view(source_message)

        await switch_thread_tag(
            thread=source_channel if isinstance(source_channel, Thread) else None,
            before_tag_id=JUDGE_TAGS.PROF_PASS,
            after_tag_id=JUDGE_TAGS.INT_PASS,
            archived=False,
        )

        pass_embed = Judging_Interview_Pass_Embed()
        try:
            await target.send(embed=pass_embed)
        except Exception:
            date_tc_id = MAIN_CHANNELS.SERVER_GUIDANCE
            date_tc = guild.get_channel(date_tc_id) or await guild.fetch_channel(date_tc_id)
            await date_tc.send(content=f"{target.mention}", embed=pass_embed)

    async def _run_interview_fail(
        self,
        *,
        interaction: Interaction,
        target: discord.Member,
        source_message: Optional[discord.Message],
        source_channel: Optional[discord.abc.GuildChannel | Thread],
    ):
        try:
            await target.kick(reason="面接不合格のため")
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="キック権限がありません。",
                embed=None,
                view=None,
            )
            return

        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 面接不合格
                """
            ).strip(),
            color=COLORS.BLACK,
        )

        await interaction.edit_original_response(
            content=None,
            embed=result_embed,
            view=None,
        )

        await self._clear_source_view(source_message)

        await switch_thread_tag(
            thread=source_channel if isinstance(source_channel, Thread) else None,
            before_tag_id=JUDGE_TAGS.PROF_PASS,
            after_tag_id=JUDGE_TAGS.FAIL,
            archived=True,
        )


class Judging_Action_Cancel_Button(Button):
    def __init__(self):
        super().__init__(
            label="やめとく",
            emoji=DEFAULT.TRASH,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        await interaction.response.edit_message(
            content="操作をキャンセルしました。",
            embed=None,
            view=None,
        )


# =========================================================
# Vote Panel
# =========================================================

class Judging_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Vote_Button(label="おすすめ", emoji=None, style=ButtonStyle.green, row=0, btn_type="FAVORITE"))
        self.add_item(Vote_Button(label="⭕️", emoji=None, style=ButtonStyle.blurple, row=0, btn_type="CIRCLE"))
        self.add_item(Vote_Button(label="❌️", emoji=None, style=ButtonStyle.gray, row=0, btn_type="CROSS"))
        self.add_item(Caution_Button(label="注意情報", emoji=None, style=ButtonStyle.red, row=1, btn_type="CAUTION"))


class Vote_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}"
        )
        self.btn_type = btn_type
        self.fs_judging = FS_Judging()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        embed = get_first_embed_from_message(interaction.message)

        if guild is None:
            await interaction.followup.send("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        if embed is None:
            await interaction.followup.send("対象Embedが見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_url(embed)
        if target_id is None:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target = await resolve_target_member(guild, target_id)
        if target is None:
            await interaction.followup.send("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return

        date_ymd = extract_date_ymd(embed)
        if date_ymd is None:
            await interaction.followup.send("日付情報を取得できませんでした。", ephemeral=True)
            return

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

        before_label = LABEL_MAP.get(before_cat)

        result = await self.fs_judging.set_vote(
            category=self.btn_type,
            target_id=target_id,
            message_id=interaction.message.id,
            date_ymd=date_ymd,
            user=interaction.user,
            comment=None,
        )

        if result == "add":
            result_embed = Judging_Result_Embed(label=self.label, target=target)
        elif result == "change":
            result_embed = Judging_Result_Change_Embed(
                before=before_label,
                label=self.label,
                target=target,
            )
        elif result == "remove":
            result_embed = Judging_Result_Clear_Embed(target=target)
        elif result == "no_change":
            result_embed = Embed(description="変更はありません。")
        else:
            result_embed = Embed(description="処理結果を判定できませんでした。")

        await interaction.followup.send(embed=result_embed, ephemeral=True)


class Caution_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}"
        )
        self.btn_type = btn_type
        self.fs_judging = FS_Judging()

    async def callback(self, interaction: Interaction):
        embed = get_first_embed_from_message(interaction.message)
        if embed is None:
            await interaction.response.send_message("対象Embedが見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_url(embed)
        if target_id is None:
            await interaction.response.send_message("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        date_ymd = extract_date_ymd(embed)
        if date_ymd is None:
            await interaction.response.send_message("日付情報を取得できませんでした。", ephemeral=True)
            return

        previous_comment = await self._get_previous_comment(
            target_id=target_id,
            message_id=interaction.message.id,
            date_ymd=date_ymd,
            voter_id=interaction.user.id,
        )

        modal = Caution_Modal(
            self.btn_type,
            target_id,
            interaction.message.id,
            date_ymd,
            previous_comment,
        )
        await interaction.response.send_modal(modal)

    async def _get_previous_comment(
        self,
        *,
        target_id: int,
        message_id: int,
        date_ymd: str,
        voter_id: int,
    ) -> Optional[str]:
        try:
            caution_data = await self.fs_judging.get_category(
                target_id=target_id,
                message_id=message_id,
                date_ymd=date_ymd,
                category="caution",
            )

            for item in caution_data.values():
                if str(item.get("user_id")) == str(voter_id):
                    return item.get("comment")
            return None

        except Exception:
            logger.exception("[%s] failed to fetch previous caution comment", FILENAME)
            return None


class Caution_Modal(Modal):
    def __init__(self, btn_type, target_id, message_id, date_ymd, previous_comment=None):
        super().__init__(title="注意情報記載", timeout=None)

        self.btn_type = btn_type
        self.target_id = target_id
        self.message_id = message_id
        self.date_ymd = date_ymd
        self.previous_comment = previous_comment
        self.fs_judging = FS_Judging()

        self.comment_input = TextInput(
            label="理由",
            style=TextStyle.paragraph,
            placeholder=textwrap.dedent(
                """
                注意情報を記載してください。
                いただいた情報は管理内でしか共有されません。
                """
            ).strip(),
            required=True,
            max_length=800,
            default=previous_comment if previous_comment else "",
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        target = await resolve_target_member(guild, self.target_id)
        if target is None:
            await interaction.followup.send("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return

        result = await self.fs_judging.set_vote(
            category=self.btn_type,
            target_id=self.target_id,
            message_id=self.message_id,
            date_ymd=self.date_ymd,
            user=interaction.user,
            comment=self.comment_input.value,
        )

        if result == "error_occurred":
            await interaction.followup.send("入力できませんでした。再度お試しください。", ephemeral=True)
            return

        result_embed = Judging_Caution_Embed(
            before=self.previous_comment,
            after=self.comment_input.value,
            target=target,
        )

        await interaction.followup.send(embed=result_embed, ephemeral=True)


# =========================================================
# Result Panel
# =========================================================

class Judging_Result_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Check_Button(label="確認", emoji=DEFAULT.EYES, style=ButtonStyle.green, row=0))
        self.add_item(Prof_Pass_Button(label="プロフ合格", emoji=DEFAULT.CIRCLE, style=ButtonStyle.blurple, row=1))
        self.add_item(Prof_Fail_Button(label="プロフ不合格", emoji=DEFAULT.CROSS, style=ButtonStyle.gray, row=1))


class Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )
        self.fs_judging = FS_Judging()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)

        embed = get_first_embed_from_message(interaction.message)
        if embed is None:
            await interaction.followup.send("対象Embedが見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_url(embed)
        if target_id is None:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        date_ymd = extract_date_ymd(embed)
        if date_ymd is None:
            await interaction.followup.send("日付情報を取得できませんでした。", ephemeral=True)
            return

        data = await self.fs_judging.get_all_for_target_date(
            target_id=target_id,
            date_ymd=date_ymd,
        )

        category_info = {
            "favorite": {"title": "おすすめ", "color": COLORS.BLUE},
            "circle": {"title": "⭕️", "color": COLORS.GREEN_LIGHT},
            "cross": {"title": "❌️", "color": COLORS.YELLOW},
            "caution": {"title": "注意情報", "color": COLORS.RED},
        }

        merged = {
            "favorite": [],
            "circle": [],
            "cross": [],
            "caution": [],
        }

        for _, info in data.items():
            for cat in ("favorite", "circle", "cross", "caution"):
                for idx, entry in sorted(info.get(cat, {}).items(), key=lambda x: int(x[0])):
                    if cat == "caution":
                        merged[cat].append(
                            f"{idx}. {entry['user_name']} (<@{entry['user_id']}>)\n　{entry.get('comment', '')}"
                        )
                    else:
                        merged[cat].append(
                            f"{idx}. {entry['user_name']} (<@{entry['user_id']}>)"
                        )

        embeds: list[discord.Embed] = []

        for cat, entries in merged.items():
            if not entries:
                continue

            title = category_info[cat]["title"]
            color = category_info[cat]["color"]

            page_text = ""
            page_num = 1

            for line in entries:
                if len(page_text) + len(line) + 2 > 4000:
                    page_embed = discord.Embed(
                        title=f"{title} ({page_num})",
                        description=page_text,
                        color=color,
                    )
                    embeds.append(page_embed)
                    page_text = ""
                    page_num += 1

                page_text += line + "\n"

            if page_text:
                page_embed = discord.Embed(
                    title=f"{title} ({page_num})",
                    description=page_text,
                    color=color,
                )
                embeds.append(page_embed)

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
        guild = interaction.guild
        embed = get_first_embed_from_message(interaction.message)

        if guild is None:
            await interaction.response.send_message("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        if embed is None:
            await interaction.response.send_message("プロフィール情報が見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_url(embed)
        if target_id is None:
            await interaction.response.send_message("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target = await resolve_target_member(guild, target_id)
        if target is None:
            await interaction.response.send_message(
                "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                ephemeral=True,
            )
            return

        confirm_embed = build_action_confirm_embed(
            target_user=target,
            action_label="プロフ合格",
        )

        await interaction.response.send_message(
            embed=confirm_embed,
            view=Judging_Action_Confirm_View(
                action_type="prof_pass",
                target_id=target.id,
                source_channel_id=interaction.channel_id,
                source_message_id=interaction.message.id,
            ),
            ephemeral=True,
        )


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
        guild = interaction.guild
        embed = get_first_embed_from_message(interaction.message)

        if guild is None:
            await interaction.response.send_message("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        if embed is None:
            await interaction.response.send_message("プロフィール情報が見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_url(embed)
        if target_id is None:
            await interaction.response.send_message("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target = await resolve_target_member(guild, target_id)
        if target is None:
            await interaction.response.send_message(
                "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                ephemeral=True,
            )
            return

        confirm_embed = build_action_confirm_embed(
            target_user=target,
            action_label="プロフ不合格",
        )

        await interaction.response.send_message(
            embed=confirm_embed,
            view=Judging_Action_Confirm_View(
                action_type="prof_fail",
                target_id=target.id,
                source_channel_id=interaction.channel_id,
                source_message_id=interaction.message.id,
            ),
            ephemeral=True,
        )


# =========================================================
# Interview
# =========================================================

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
        guild = interaction.guild
        embed = get_first_embed_from_message(interaction.message)

        if guild is None:
            await interaction.response.send_message("ギルド情報が取得できません。", ephemeral=True)
            return

        if embed is None:
            await interaction.response.send_message("対象Embedが見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_name(embed)
        if target_id is None:
            await interaction.response.send_message("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target = await resolve_target_member(guild, target_id)
        if target is None:
            await interaction.response.send_message(
                "このメンバーはサーバーから脱退しています。",
                ephemeral=True,
            )
            return

        confirm_embed = build_action_confirm_embed(
            target_user=target,
            action_label="面接合格",
        )

        await interaction.response.send_message(
            embed=confirm_embed,
            view=Judging_Action_Confirm_View(
                action_type="interview_pass",
                target_id=target.id,
                source_channel_id=interaction.channel_id,
                source_message_id=interaction.message.id,
            ),
            ephemeral=True,
        )


class Interview_Fail_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        guild = interaction.guild
        embed = get_first_embed_from_message(interaction.message)

        if guild is None:
            await interaction.response.send_message("ギルド情報を取得できませんでした。", ephemeral=True)
            return

        if embed is None:
            await interaction.response.send_message("対象Embedが見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_name(embed)
        if target_id is None:
            await interaction.response.send_message("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target = await resolve_target_member(guild, target_id)
        if target is None:
            await interaction.response.send_message(
                "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                ephemeral=True,
            )
            return

        confirm_embed = build_action_confirm_embed(
            target_user=target,
            action_label="面接不合格",
        )

        await interaction.response.send_message(
            embed=confirm_embed,
            view=Judging_Action_Confirm_View(
                action_type="interview_fail",
                target_id=target.id,
                source_channel_id=interaction.channel_id,
                source_message_id=interaction.message.id,
            ),
            ephemeral=True,
        )


# =========================================================
# Guidance
# =========================================================

class Server_Guidance_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Guidance_Start_Button(label="説明開始", emoji=DEFAULT.NEXT, style=ButtonStyle.gray, row=0))
        self.add_item(Guidance_Pass_Button(label="説明完了", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=0))


class Guidance_Start_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()

        guild = interaction.guild
        embed = get_first_embed_from_message(interaction.message)

        if guild is None:
            await interaction.followup.send("ギルド情報が取得できません。", ephemeral=True)
            return

        if embed is None:
            await interaction.followup.send("対象Embedが見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_name(embed)
        if target_id is None:
            await interaction.followup.send("対象ユーザーIDがEmbedにありません。", ephemeral=True)
            return

        target = await resolve_target_member(guild, target_id)
        if target is None:
            await interaction.followup.send(
                "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                ephemeral=True,
            )
            return

        add_role_ids = [
            MAIN_ROLES.P_MEMBER,
        ]
        remove_role_ids = []

        if has_any_role(target, [MAIN_ROLES.G_MALE]) and not has_any_role(target, [MAIN_ROLES.G_FEMALE]):
            add_role_ids.append(MAIN_ROLES.P_MALE)
            remove_role_ids.append(MAIN_ROLES.G_MALE)

        elif has_any_role(target, [MAIN_ROLES.G_FEMALE]) and not has_any_role(target, [MAIN_ROLES.G_MALE]):
            add_role_ids.append(MAIN_ROLES.P_FEMALE)
            remove_role_ids.append(MAIN_ROLES.G_FEMALE)

        else:
            await interaction.followup.send(
                "性別ロール（G_MALE/G_FEMALE）の判定ができませんでした。スタッフが確認してください。",
                ephemeral=True,
            )
            return

        role_ids_now = {r.id for r in target.roles}

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

        roles_to_add = list({r.id: r for r in roles_to_add}.values())
        roles_to_remove = list({r.id: r for r in roles_to_remove}.values())

        if not roles_to_add:
            await interaction.followup.send("付与するロールが見つかりませんでした。", ephemeral=True)
            return

        roles_to_add = [r for r in roles_to_add if r.id not in role_ids_now]
        roles_to_remove = [r for r in roles_to_remove if r.id in role_ids_now]

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
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )
        self.temp_judging_service = TempJudgingService()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()

        guild = interaction.guild
        embed = get_first_embed_from_message(interaction.message)

        if guild is None:
            await interaction.followup.send("ギルド情報が取得できません。", ephemeral=True)
            return

        if embed is None:
            await interaction.followup.send("対象Embedが見つかりません。", ephemeral=True)
            return

        target_id = extract_user_id_from_author_name(embed)
        if target_id is None:
            await interaction.followup.send("対象ユーザーIDがEmbedにありません。", ephemeral=True)
            return

        target = await resolve_target_member(guild, target_id)
        if target is None:
            await interaction.followup.send(
                "対象ユーザーがサーバーに存在しません（退会 / BAN の可能性）。",
                ephemeral=True,
            )
            return

        remove_role_ids = [
            MAIN_ROLES.SERVER_GUIDANCE,
            MAIN_ROLES.PROF_PASS,
            MAIN_ROLES.GUEST,
        ]

        role_ids_now = {r.id for r in target.roles}

        roles_to_remove = []
        for rid in remove_role_ids:
            role = await resolve_role(guild=guild, role_id=rid)
            if role is not None:
                roles_to_remove.append(role)

        roles_to_remove = list({r.id: r for r in roles_to_remove}.values())
        roles_to_remove = [r for r in roles_to_remove if r.id in role_ids_now]

        try:
            if roles_to_remove:
                await target.remove_roles(*roles_to_remove, reason="案内完了（入口ロール解除）")
        except discord.Forbidden:
            await interaction.followup.send("ロール編集の権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"ロール更新に失敗しました: {e}", ephemeral=True)
            return

        await switch_thread_tag(
            thread=interaction.channel if isinstance(interaction.channel, Thread) else None,
            before_tag_id=JUDGE_TAGS.INT_PASS,
            after_tag_id=JUDGE_TAGS.PASS,
            archived=True,
        )

        try:
            user_forum = guild.get_channel(MAIN_CHANNELS.TEMP_JUDGE_USER_FORUM)
            if user_forum is None:
                user_forum = await guild.fetch_channel(MAIN_CHANNELS.TEMP_JUDGE_USER_FORUM)

            admin_forum = guild.get_channel(MAIN_CHANNELS.TEMP_JUDGE_ADMIN_FORUM)
            if admin_forum is None:
                admin_forum = await guild.fetch_channel(MAIN_CHANNELS.TEMP_JUDGE_ADMIN_FORUM)

            if not isinstance(user_forum, discord.ForumChannel):
                await interaction.followup.send(
                    "メンバー用仮免審査フォーラムを取得できませんでした。",
                    ephemeral=True,
                )
                return

            if not isinstance(admin_forum, discord.ForumChannel):
                await interaction.followup.send(
                    "管理用仮免審査フォーラムを取得できませんでした。",
                    ephemeral=True,
                )
                return

            await self.temp_judging_service.create_temp_judge_panel(
                guild=guild,
                member=target,
                user_forum=user_forum,
                admin_forum=admin_forum,
            )

        except Exception as e:
            await interaction.followup.send(f"仮免審査パネル作成に失敗しました: {e}", ephemeral=True)
            return

        await interaction.edit_original_response(
            content="案内完了。入口ロールを外し、仮免審査フォーラムを作成しました。",
            view=None,
        )


# =========================================================
# Guide Panel
# =========================================================

class Guide_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Guidance_Start_VC_Member_Button(label="VCメンバーに案内開始", emoji=DEFAULT.NEXT, style=ButtonStyle.gray, row=0))


class Guidance_Start_VC_Member_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("guild を取得できませんでした。", ephemeral=True)
            return

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

        exclude_role_ids: set[int] = {
            MAIN_ROLES.GUIDE,
        }
        exclude_bots = True

        base_add_role_ids = [
            MAIN_ROLES.P_MEMBER,
        ]
        base_remove_role_ids: list[int] = []

        all_possible_role_ids: set[int] = set(base_add_role_ids) | set(base_remove_role_ids)
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

        if MAIN_ROLES.P_MEMBER not in role_map:
            await interaction.followup.send("付与するロール（P_MEMBER）が見つかりませんでした。", ephemeral=True)
            return

        vc_members = list(vc.members)

        targets: list[discord.Member] = []
        excluded: list[discord.Member] = []

        for member in vc_members:
            if exclude_bots and member.bot:
                excluded.append(member)
                continue

            if has_any_role(member, exclude_role_ids):
                excluded.append(member)
                continue

            targets.append(member)

        if not targets:
            await interaction.followup.send(
                "対象ユーザーがいませんでした（除外条件により全員対象外の可能性）。",
                ephemeral=True,
            )
            return

        granted_users_lines: list[str] = []
        failed_users_lines: list[str] = []
        used_role_ids: set[int] = set()

        for member in targets:
            add_role_ids = list(base_add_role_ids)
            remove_role_ids = list(base_remove_role_ids)

            if has_any_role(member, [MAIN_ROLES.G_MALE]) and not has_any_role(member, [MAIN_ROLES.G_FEMALE]):
                add_role_ids.append(MAIN_ROLES.P_MALE)
                remove_role_ids.append(MAIN_ROLES.G_MALE)

            elif has_any_role(member, [MAIN_ROLES.G_FEMALE]) and not has_any_role(member, [MAIN_ROLES.G_MALE]):
                add_role_ids.append(MAIN_ROLES.P_FEMALE)
                remove_role_ids.append(MAIN_ROLES.G_FEMALE)

            else:
                failed_users_lines.append(
                    f"- {member.mention}：性別ロール判定不可（G_MALE/G_FEMALE）"
                )
                continue

            role_ids_now = {r.id for r in member.roles}

            roles_to_add = [role_map[rid] for rid in add_role_ids if rid in role_map]
            roles_to_remove = [role_map[rid] for rid in remove_role_ids if rid in role_map]

            roles_to_add = [r for r in roles_to_add if r.id not in role_ids_now]
            roles_to_remove = [r for r in roles_to_remove if r.id in role_ids_now]

            if not roles_to_add and not roles_to_remove:
                granted_users_lines.append(f"- {member.mention}：変更なし")
                continue

            try:
                if roles_to_add:
                    await member.add_roles(*roles_to_add, reason="案内開始（VC接続メンバー一括）")
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason="案内開始（入口男女解除）")

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

        used_roles = [role_map[rid].mention for rid in used_role_ids if rid in role_map]
        if not used_roles:
            used_roles = ["(なし)"]

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
            value=chunk_lines(granted_users_lines),
            inline=False,
        )
        if failed_users_lines:
            embed.add_field(
                name="失敗/スキップ（要確認）",
                value=chunk_lines(failed_users_lines),
                inline=False,
            )

        await interaction.edit_original_response(content=None, embed=embed, view=None)