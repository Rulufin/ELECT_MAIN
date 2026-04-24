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

from firestores.fs_judging_temp import FS_Judging_Temp
from firestores.fs_talk_history import FS_Talk_History

from services.judging.temp.ui.embeds import (
    Judging_Result_Embed, Judging_Result_Change_Embed, Judging_Result_Clear_Embed,
    Judging_Caution_Embed, JT_Pass_Embed
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

FILENAME = "judging_temp_views"

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Tokyo")

LABEL_MAP = {
    "circle": "⭕️",
    "cross": "❌️",
    "caution": "注意",
}


class JT_User_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(JT_OK_Button(label="⭕️", emoji=None, style=ButtonStyle.blurple, row=0, btn_type="CIRCLE"))
        self.add_item(JT_Reason_Vote_Button(label="❌️", emoji=None, style=ButtonStyle.gray, row=0, btn_type="CROSS"))
        self.add_item(JT_Reason_Vote_Button(label="注意情報", emoji=None, style=ButtonStyle.red, row=1, btn_type="CAUTION"))


class JT_OK_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}"
        )
        self.btn_type = btn_type
        self.fs_judging = FS_Judging_Temp()
        self.fs_history = FS_Talk_History()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        match = re.search(r"(\d{15,25})", author_url or "")
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target_id = int(match.group(1))
        voter_id = int(interaction.user.id)

        if target_id == voter_id:
            await interaction.followup.send("自分自身には投票できません。", ephemeral=True)
            return

        try:
            target = interaction.guild.get_member(target_id) or await interaction.guild.fetch_member(target_id)
        except Exception as e:
            logger.error(f"Error while fetching member: {e}")
            await interaction.followup.send("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return

        can_vote = await self.fs_history.can_vote_for(
            voter_id=voter_id,
            target_id=target_id,
        )
        if not can_vote:
            await interaction.followup.send(
                "このユーザーにはまだ投票できません。一定時間以上VCで同席した相手のみ投票できます。",
                ephemeral=True
            )
            return

        date_ymd = embed.footer.text

        before_cat = await self._get_before_category(
            target_id=target_id,
            voter_id=voter_id,
            message_id=interaction.message.id,
            date_ymd=date_ymd,
        )
        before_label = LABEL_MAP.get(before_cat)

        vote_result = await self.fs_judging.set_vote(
            category=self.btn_type,
            target_id=target_id,
            message_id=interaction.message.id,
            date_ymd=date_ymd,
            user=interaction.user,
            comment=None,
        )

        if vote_result == "add":
            result_embed = Judging_Result_Embed(label=self.label, target=target)

        elif vote_result == "change":
            result_embed = Judging_Result_Change_Embed(
                before=before_label,
                label=self.label,
                target=target,
            )

        elif vote_result == "remove":
            result_embed = Judging_Result_Clear_Embed(target=target)

        elif vote_result == "no_change":
            result_embed = Embed(description="変更はありません。")

        else:
            result_embed = Embed(description="投票処理中に不明な結果が返されました。")

        await interaction.followup.send(embed=result_embed, ephemeral=True)

    async def _get_before_category(self, target_id, voter_id, message_id, date_ymd):
        for cat in ["circle", "cross", "caution"]:
            cat_map = await self.fs_judging.get_category(
                target_id=target_id,
                message_id=message_id,
                date_ymd=date_ymd,
                category=cat,
            )
            for item in cat_map.values():
                if item.get("user_id") == str(voter_id):
                    return cat
        return None


class JT_Reason_Vote_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}"
        )
        self.btn_type = btn_type
        self.fs_judging = FS_Judging_Temp()
        self.fs_history = FS_Talk_History()

    async def callback(self, interaction: Interaction):
        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        match = re.search(r"(\d{15,25})", author_url or "")
        if not match:
            await interaction.response.send_message("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target_id = int(match.group(1))
        voter_id = int(interaction.user.id)

        if target_id == voter_id:
            await interaction.response.send_message("自分自身には投票できません。", ephemeral=True)
            return

        try:
            interaction.guild.get_member(target_id) or await interaction.guild.fetch_member(target_id)
        except Exception as e:
            logger.error(f"Error while fetching member: {e}")
            await interaction.response.send_message("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return

        if self.btn_type != "CAUTION":
            can_vote = await self.fs_history.can_vote_for(
                voter_id=voter_id,
                target_id=target_id,
            )
            if not can_vote:
                await interaction.response.send_message(
                    "このユーザーにはまだ投票できません。一定時間以上VCで同席した相手のみ投票できます。",
                    ephemeral=True
                )
                return

        date_ymd = embed.footer.text
        previous_comment = await self._get_previous_comment(
            target_id=target_id,
            voter_id=voter_id,
            message_id=interaction.message.id,
            date_ymd=date_ymd,
        )

        modal = JT_Reason_Vote_Modal(
            btn_type=self.btn_type,
            target_id=target_id,
            date_ymd=date_ymd,
            previous_comment=previous_comment,
        )
        await interaction.response.send_modal(modal)

    async def _get_previous_comment(self, target_id, voter_id, message_id, date_ymd):
        category = self.btn_type.lower()

        try:
            category_data = await self.fs_judging.get_category(
                target_id=target_id,
                message_id=message_id,
                date_ymd=date_ymd,
                category=category,
            )
            for item in category_data.values():
                if item.get("user_id") == str(voter_id):
                    return item.get("comment")
            return None

        except Exception as e:
            logger.error(f"Error while fetching previous comment: {e}")
            return None


class JT_Reason_Vote_Modal(Modal):
    def __init__(self, btn_type, target_id, date_ymd, previous_comment=None):
        title_map = {
            "CROSS": "NG理由記載",
            "CAUTION": "注意情報記載",
        }
        placeholder_map = {
            "CROSS": """
            NGの理由を記載してください。
            いただいた情報は管理内でしか共有されません。
            """,
            "CAUTION": """
            注意情報を記載してください。
            いただいた情報は管理内でしか共有されません。
            """,
        }

        super().__init__(title=title_map.get(btn_type, "理由記載"), timeout=None)

        self.btn_type = btn_type
        self.target_id = target_id
        self.date_ymd = date_ymd
        self.fs_judging = FS_Judging_Temp()

        self.comment_input = TextInput(
            label="理由",
            style=TextStyle.paragraph,
            placeholder=textwrap.dedent(placeholder_map.get(btn_type, "理由を記載してください。")).strip(),
            required=True,
            max_length=800,
            default=previous_comment or "",
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            target = interaction.guild.get_member(self.target_id) or await interaction.guild.fetch_member(self.target_id)
        except Exception as e:
            logger.error(f"Error while fetching member during modal submission: {e}")
            await interaction.followup.send("審査対象者がサーバーを脱退しています。", ephemeral=True)
            return

        before_cat = await self._get_before_category(
            voter_id=interaction.user.id,
            message_id=interaction.message.id,
        )
        before_label = LABEL_MAP.get(before_cat)

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

        current_label = "❌️" if self.btn_type == "CROSS" else "注意"

        if result == "add":
            result_embed = Judging_Result_Embed(label=current_label, target=target)

        elif result == "change":
            if self.btn_type == "CAUTION" and before_cat == "caution":
                result_embed = Judging_Caution_Embed(
                    before=self.comment_input.default,
                    after=self.comment_input.value,
                    target=target,
                )
            else:
                result_embed = Judging_Result_Change_Embed(
                    before=before_label,
                    label=current_label,
                    target=target,
                )

        elif result == "remove":
            result_embed = Judging_Result_Clear_Embed(target=target)

        elif result == "no_change":
            result_embed = Embed(description="変更はありません。")

        else:
            result_embed = Embed(description="投票処理中に不明な結果が返されました。")

        await interaction.followup.send(embed=result_embed, ephemeral=True)

    async def _get_before_category(self, voter_id, message_id):
        for cat in ["circle", "cross", "caution"]:
            cat_map = await self.fs_judging.get_category(
                target_id=self.target_id,
                message_id=message_id,
                date_ymd=self.date_ymd,
                category=cat,
            )
            for item in cat_map.values():
                if item.get("user_id") == str(voter_id):
                    return cat
        return None


class JT_Result_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(JT_Check_Button(label="確認", emoji=DEFAULT.EYES, style=ButtonStyle.green, row=0))
        self.add_item(Temp_Pass_Button(label="仮免合格", emoji=DEFAULT.CIRCLE, style=ButtonStyle.blurple, row=1))
        self.add_item(Temp_Fail_Button(label="仮免不合格", emoji=DEFAULT.CROSS, style=ButtonStyle.gray, row=1))


class JT_Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_judging = FS_Judging_Temp()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        match = re.search(r"(\d{15,25})", author_url or "")
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return
        target_id = int(match.group(1))

        date_ymd = embed.footer.text

        data = await self.fs_judging.get_all_for_target_date(target_id=target_id, date_ymd=date_ymd)

        CATEGORY_INFO = {
            "circle": {"title": "⭕️", "color": COLORS.GREEN_LIGHT},
            "cross": {"title": "❌️", "color": COLORS.YELLOW},
            "caution": {"title": "注意情報", "color": COLORS.RED},
        }

        merged = {
            "circle": [],
            "cross": [],
            "caution": [],
        }

        for msg_id, info in data.items():
            for cat in ("circle", "cross", "caution"):
                for idx, entry in sorted(info.get(cat, {}).items(), key=lambda x: int(x[0])):
                    if cat in ("cross", "caution"):
                        merged[cat].append(
                            f"{entry['user_name']} (<@{entry['user_id']}>)\n　{entry.get('comment', '')}"
                        )
                    else:
                        merged[cat].append(
                            f"{entry['user_name']} (<@{entry['user_id']}>)"
                        )

        embeds: list[discord.Embed] = []

        for cat, entries in merged.items():
            if not entries:
                continue

            title = CATEGORY_INFO[cat]["title"]
            color = CATEGORY_INFO[cat]["color"]

            page_text = ""
            page_num = 1

            for i, line in enumerate(entries, start=1):
                numbered_line = f"{i}. {line}"

                if len(page_text) + len(numbered_line) + 2 > 4000:
                    result_embed = discord.Embed(
                        title=f"{title} ({page_num})",
                        description=page_text,
                        color=color,
                    )
                    embeds.append(result_embed)
                    page_text = ""
                    page_num += 1

                page_text += numbered_line + "\n"

            if page_text:
                result_embed = discord.Embed(
                    title=f"{title} ({page_num})",
                    description=page_text,
                    color=color,
                )
                embeds.append(result_embed)

        if not embeds:
            await interaction.followup.send("データがありません。", ephemeral=True)
            return

        for result_embed in embeds:
            await interaction.followup.send(embed=result_embed)


class Temp_Pass_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )
        self.fs_judging_temp = FS_Judging_Temp()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)

        embed = interaction.message.embeds[0]
        author_url = embed.author.url

        guild = interaction.guild
        if guild is None:
            await interaction.edit_original_response(content="⚠️ ギルド情報が取得できません。", view=None)
            return

        if not author_url:
            await interaction.followup.send("対象ユーザーの情報URLが見つかりません。", ephemeral=True)
            return

        match = re.search(r"(\d{15,25})", author_url)
        if not match:
            await interaction.followup.send("対象ユーザーIDを抽出できませんでした。", ephemeral=True)
            return

        target_id = int(match.group(1))

        try:
            target = guild.get_member(target_id) or await guild.fetch_member(target_id)
        except Exception:
            logger.error(f"Member Not Found: {target_id}")
            await interaction.edit_original_response(
                content="⚠️ このメンバーはサーバーから脱退しています。",
                view=None,
            )
            return

        add_role_ids = [
            MAIN_ROLES.MEMBER,
        ]

        remove_role_ids = [
            MAIN_ROLES.P_MEMBER,
        ]

        if MAIN_ROLES.P_MALE in {r.id for r in target.roles}:
            add_role_ids.append(MAIN_ROLES.MALE)
            remove_role_ids.append(MAIN_ROLES.P_MALE)
        else:
            add_role_ids.append(MAIN_ROLES.FEMALE)
            remove_role_ids.append(MAIN_ROLES.P_FEMALE)

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

        try:
            await target.add_roles(*roles_to_add, reason="面接合格")

            if roles_to_remove:
                await target.remove_roles(*roles_to_remove, reason="面接合格（旧ロール解除）")

        except discord.Forbidden:
            await interaction.followup.send("ロール編集の権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"ロール更新に失敗しました: {e}", ephemeral=True)
            return

        result_embed = Embed(
            description=textwrap.dedent(
                f"""
                {target.display_name} ({target.mention})
                # 仮免合格
                """
            ),
            color=COLORS.BLUE_LIGHTSKY,
        )
        result_embed.set_author(name=f"{target_id}")

        await interaction.followup.send(embed=result_embed)
        await interaction.message.edit(view=None)

        admin_thread = interaction.channel
        if isinstance(admin_thread, discord.Thread):
            before_tag_id = JUDGE_TAGS.TEMP_NOW
            after_tag_id = JUDGE_TAGS.TEMP_PASS

            new_tags = [
                tag for tag in admin_thread.applied_tags
                if tag.id != before_tag_id
            ]

            if not any(tag.id == after_tag_id for tag in new_tags):
                forum = admin_thread.parent
                if forum and isinstance(forum, ForumChannel):
                    after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
                    if after_tag:
                        new_tags.append(after_tag)

            await admin_thread.edit(applied_tags=new_tags, archived=True)

        try:
            admin_thread_id = interaction.channel.id if interaction.channel else None
            if admin_thread_id is not None:
                entry = await self.fs_judging_temp.get_entry_by_target_and_admin_thread_id(
                    target_id=target_id,
                    admin_thread_id=admin_thread_id,
                )
                user_thread_id = entry.get("user_thread_id") if entry else None

                if user_thread_id:
                    user_thread_id = int(user_thread_id)

                    if user_thread_id != admin_thread_id:
                        user_thread = guild.get_channel(user_thread_id)
                        if user_thread is None:
                            try:
                                user_thread = await guild.fetch_channel(user_thread_id)
                            except Exception:
                                user_thread = None

                        if isinstance(user_thread, discord.Thread):
                            await user_thread.delete(reason="仮免合格のためユーザー側スレッドを削除")
        except Exception:
            logger.exception(
                "[%s] failed to delete user thread on pass target_id=%s",
                FILENAME,
                target_id,
            )

        pass_embed = JT_Pass_Embed()
        try:
            await target.send(embed=pass_embed)
        except Exception:
            pass


class Temp_Fail_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )
        self.fs_judging_temp = FS_Judging_Temp()

    async def callback(self, interaction: Interaction):
        try:
            await interaction.response.defer(thinking=True)
        except discord.NotFound:
            return

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

        try:
            await target.kick(reason="仮免審査不合格のため")
        except discord.Forbidden:
            await interaction.followup.send("キック権限がありません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"キックに失敗しました: {e}", ephemeral=True)
            return

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

        admin_thread = interaction.channel
        if isinstance(admin_thread, Thread):
            before_tag_id = JUDGE_TAGS.TEMP_NOW
            after_tag_id = JUDGE_TAGS.TEMP_FAIL

            new_tags = [
                tag for tag in admin_thread.applied_tags
                if tag.id != before_tag_id
            ]

            if not any(tag.id == after_tag_id for tag in new_tags):
                forum = admin_thread.parent
                if forum and isinstance(forum, ForumChannel):
                    after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
                    if after_tag:
                        new_tags.append(after_tag)

            await admin_thread.edit(applied_tags=new_tags, archived=True)

        try:
            admin_thread_id = interaction.channel.id if interaction.channel else None
            if admin_thread_id is not None:
                entry = await self.fs_judging_temp.get_entry_by_target_and_admin_thread_id(
                    target_id=target_id,
                    admin_thread_id=admin_thread_id,
                )
                user_thread_id = entry.get("user_thread_id") if entry else None

                if user_thread_id:
                    user_thread_id = int(user_thread_id)

                    if user_thread_id != admin_thread_id:
                        user_thread = guild.get_channel(user_thread_id)
                        if user_thread is None:
                            try:
                                user_thread = await guild.fetch_channel(user_thread_id)
                            except Exception:
                                user_thread = None

                        if isinstance(user_thread, Thread):
                            await user_thread.delete(reason="仮免不合格のためユーザー側スレッドを削除")
        except Exception:
            logger.exception(
                "[%s] failed to delete user thread on fail target_id=%s",
                FILENAME,
                target_id,
            )