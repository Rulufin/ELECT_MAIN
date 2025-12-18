import discord
from discord.ext import commands, tasks
from discord import (
    app_commands, Interaction, PermissionOverwrite,
    SelectOption, TextStyle, ChannelType, ButtonStyle,
    Member, User, Thread, TextChannel, VoiceChannel, ForumChannel, Guild,
    Emoji, PartialEmoji,
)

from discord.ui import (
    View, Button, Modal, Select,
    TextInput
)
from discord.errors import HTTPException
from discord.utils import get
import gspread
from google.oauth2.service_account import Credentials
import asyncio
import re
import logging
import aiohttp
import os
import pytz
import textwrap
from datetime import datetime, timedelta
from typing import Optional, Set, cast

from helpers.http import *

from services.voice_channel.embeds import *
from services.system.embeds import *

from firestores.fs_vc_tc_sync import FS_VC_TC_SYNC
from firestores.fs_user_info import FS_Profile

from utils.ids import *
from utils.emojis import *
from utils.colorcodes import *

from utils.discord.latelimit import check_button_cooldown

FILENAME = "voice_channel_views"

logger = logging.getLogger(__name__)

# 会議
class Group_Knock_Menu_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Name_Change_Button(label="部屋名変更", emoji=DEFAULT.MEMO, style=ButtonStyle.gray, row=0))
        self.add_item(UserLimit_Change_Button(label="人数変更", emoji=DEFAULT.PEOPLE_TWO, style=ButtonStyle.gray, row=0))
        self.add_item(Bitrate_Change_Button(label="ビットレート変更", emoji=DEFAULT.HEADPHONE, style=ButtonStyle.gray, row=1))
        self.add_item(Knock_Button(label="ノック", emoji=DEFAULT.DOOR, style=ButtonStyle.green, row=2))

class Name_Change_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        raw_name = interaction.channel.name
        door = str(DEFAULT.DOOR)

        if raw_name.startswith(door):
            cleaned_name = raw_name[len(door):].lstrip()
        else:
            cleaned_name = raw_name

        modal = Name_Change_Modal(def_name=cleaned_name)
        await interaction.response.send_modal(modal)

class Name_Change_Modal(Modal):
    def __init__(self, def_name):
        super().__init__(title="部屋名変更", timeout=None)
        self.def_name = def_name
        self.name_input = TextInput(
            label="部屋名",
            default=def_name,
            placeholder="部屋名を入力してください。",
            required=True,
            max_length=80,
        )
        self.status_input = TextInput(
            label="チャンネルステータス",
            placeholder=textwrap.dedent(
                '''
                ステータスを入力してください。
                -# 未入力だと変更しません。
                '''
            ),
            max_length=80,
            required=False
        )
        self.add_item(self.name_input)
        self.add_item(self.status_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()
        
        new_name_text = self.name_input.value

        new_name = f"{DEFAULT.DOOR}{new_name_text}"

        new_status = self.status_input.value

        try:
            if new_name_text != self.def_name:
                result = await DiscordHTTP().edit_voice_channel(
                    channel_id=interaction.channel.id,
                    name=new_name,
                )

                if result.get("status") == "rate_limit":
                    retry_after = result.get("retry_after", 0)
                    embed = VC_RateLimit_Embed(retry_after=retry_after)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

                if result.get("status") == "success":
                    if new_status:
                        await interaction.channel.edit(status=new_status)  # チャンネルのステータスを編集
                    success_embed = VC_Status_Change_Embed("Name", name=new_name, status=new_status)
                    await interaction.followup.send(embed=success_embed)
                else:
                    error_embed = VC_Error_Embed()
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                if new_status:
                    await interaction.channel.edit(status=new_status)  # チャンネルのステータスを編集
                    success_embed = VC_Status_Change_Embed("Name", name=new_name, status=new_status)
                    await interaction.followup.send(embed=success_embed)
                else:
                    await interaction.followup.send("名前/ステータス変更をキャンセルしました。")
        except Exception as e:
            logger.error(f"Failed to edit channel name: {e}", exc_info=True)
            error_embed = VC_Internal_Error_Embed()
            await interaction.followup.send(embed=error_embed, ephemeral=True)

class UserLimit_Change_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        voice_state = interaction.user.voice

        if not voice_state or voice_state.channel != interaction.channel:
            await interaction.response.send_message(embed=VC_Connect_Error_Embed(interaction.channel.jump_url), ephemeral=True)
            return

        modal = UserLimit_Change_Modal(interaction.channel.user_limit)
        await interaction.response.send_modal(modal)

class UserLimit_Change_Modal(Modal):
    def __init__(self, user_limit):
        super().__init__(title="人数制限の変更")
        self.number_input = discord.ui.TextInput(
            label="空白もしくは0だと人数制限なしになります。",
            default=f"{user_limit}",
            required=False
        )
        self.add_item(self.number_input)

    def zenkaku_to_hankaku(self, s):
        """全角数字を半角数字に変換する。空白の場合は0を返す"""
        if not s.strip():  # 空白または空文字列の場合は0に変換
            return '0'
        return s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()

        # 全角を半角に変換、空白の場合は '0' にする
        numbers = self.zenkaku_to_hankaku(self.number_input.value)

        # 入力が数字でない場合、エラーを表示
        if not numbers.isdigit():
            await interaction.followup.send(embed=VC_Zenhankaku_Error_Embed(), ephemeral=True)
            return

        # 0は無制限とする
        user_limit = int(numbers)

        try:
            result = await DiscordHTTP().edit_voice_channel(
                channel_id=interaction.channel.id,
                user_limit=user_limit,
            )

            if result.get("status") == "rate_limit":
                retry_after = result.get("retry_after", 0)
                embed = VC_RateLimit_Embed(retry_after=retry_after)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if result.get("status") == "success":
                success_embed = VC_Status_Change_Embed("Limit", user_limit=user_limit)
                await interaction.followup.send(embed=success_embed)
            else:
                error_embed = VC_Error_Embed()
                await interaction.followup.send(embed=error_embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to edit channel name: {e}", exc_info=True)
            error_embed = VC_Internal_Error_Embed()
            await interaction.followup.send(embed=error_embed, ephemeral=True)

class Bitrate_Change_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        voice_state = interaction.user.voice

        if not voice_state or voice_state.channel != interaction.channel:
            await interaction.response.send_message(embed=VC_Connect_Error_Embed(interaction.channel.jump_url), ephemeral=True)
            return

        guild = interaction.guild
        channel = interaction.channel
        current_bitrate = channel.bitrate

        if guild.premium_tier == 0:
            max_bitrate = 96000  # 96kbps
        elif guild.premium_tier == 1:
            max_bitrate = 128000  # 128kbps
        elif guild.premium_tier == 2:
            max_bitrate = 256000  # 256kbps
        elif guild.premium_tier == 3:
            max_bitrate = 384000  # 384kbps

        modal = Bitrate_Change_Modal(current_bitrate, max_bitrate)
        await interaction.response.send_modal(modal)

class Bitrate_Change_Modal(Modal):
    def __init__(self, current_bitrate, max_bitrate):
        super().__init__(title="ビットレート変更")
        self.max_bitrate = max_bitrate
        self.bitrate_input = TextInput(
            label=f"8～{max_bitrate/1000}kbpsから選んで下さい。",
            default=f"{current_bitrate/1000}"
        )
        self.add_item(self.bitrate_input)

    def zenkaku_to_hankaku(self, s):
        """全角数字を半角数字に変換する"""
        return s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()
        # 入力された値を全角から半角に変換
        input_bitrate = self.zenkaku_to_hankaku(self.bitrate_input.value)

        # 変換後の入力が半角数字のみかチェック
        if not input_bitrate.isdigit():
            await interaction.followup.send(embed=VC_Zenhankaku_Error_Embed(), ephemeral=True)
            return

        # ビットレートの設定範囲チェック
        change_bitrate = int(input_bitrate) * 1000
        if not 8000 <= change_bitrate <= self.max_bitrate:
            await interaction.followup.send(VC_Bitrate_Error_Embed(self.max_bitrate), ephemeral=True)
            return

        try:
            result = await DiscordHTTP().edit_voice_channel(
                channel_id=interaction.channel.id,
                bitrate=change_bitrate,
            )

            if result.get("status") == "rate_limit":
                retry_after = result.get("retry_after", 0)
                embed = VC_RateLimit_Embed(retry_after=retry_after)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if result.get("status") == "success":
                success_embed = VC_Status_Change_Embed("Bitrate", bitrate=change_bitrate)
                await interaction.followup.send(embed=success_embed)
            else:
                error_embed = VC_Error_Embed()
                await interaction.followup.send(embed=error_embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to edit channel name: {e}", exc_info=True)
            error_embed = VC_Internal_Error_Embed()
            await interaction.followup.send(embed=error_embed, ephemeral=True)


class Sleep_Button(Button):
    def __init__(self, label: str, emoji: Optional[Emoji | PartialEmoji | str], style: ButtonStyle, row: int):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        voice_state = interaction.user.voice

        # ユーザーがVCに接続しているかチェック
        if not voice_state or not voice_state.channel:
            await interaction.response.send_message(
                embed=VC_Connect_Error_Embed(interaction.channel.jump_url),
                ephemeral=True,
            )
            return

        voice_channel = voice_state.channel

        await interaction.response.defer()

        # VC内の「他の人間」だけを対象にする
        vc_members = [
            member
            for member in voice_channel.members
            if not member.bot and member != interaction.user
        ]

        options: List[SelectOption] = [
            SelectOption(label=member.display_name, value=str(member.id))
            for member in vc_members
        ]

        if not options:
            await interaction.followup.send(
                "VCに接続している他のユーザーはいません。",
                ephemeral=True,
            )
            return

        view = Sleep_Select_Menu(options=options)
        embed = Embed(
            title="__選択: 寝落ち切断__",
            description="VCで切断するユーザーを選択してください。",
            color=discord.Color.blue(),
        ).set_footer(text=f"ページ: 1/{view.total_pages}")

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class Sleep_Select_Menu(View):
    def __init__(self, options: List[SelectOption], max_items_per_page: int = 25):
        super().__init__(timeout=None)
        self.options: List[SelectOption] = options
        self.max_items_per_page: int = max_items_per_page
        self.current_page: int = 0
        self.selected_items: Set[str] = set()
        self.total_pages: int = (len(self.options) - 1) // self.max_items_per_page + 1

        self.embed: Embed = (
            Embed(
                title="__選択: 寝落ち切断__",
                description="選択したユーザー",
            ).set_footer(text=f"ページ: 1/{self.total_pages}")
        )

        self.update_menu()

    # ─────────────────────────
    # メニュー構築
    # ─────────────────────────
    def update_menu(self) -> None:
        start = self.current_page * self.max_items_per_page
        end = start + self.max_items_per_page
        page_options = self.options[start:end]

        select_menu = Select(
            placeholder="選択してください",
            options=[
                SelectOption(
                    label=opt.label,
                    value=opt.value,
                    default=(opt.value in self.selected_items),
                )
                for opt in page_options
            ],
            max_values=len(page_options) if page_options else 1,
            min_values=0,
        )
        select_menu.callback = self.select_callback

        self.clear_items()

        if page_options:
            self.add_item(select_menu)

        # ページ切り替えボタン
        if self.current_page > 0:
            self.add_item(PrevPageButton())
        if end < len(self.options):
            self.add_item(NextPageButton())

        # 選択操作ボタン
        self.add_item(SelectAllButton())
        self.add_item(ResetSelectionButton())
        self.add_item(ConfirmButton())

    # ─────────────────────────
    # セレクトメニューのコールバック
    # ─────────────────────────
    async def select_callback(self, interaction: Interaction):
        # interaction.data["values"] から現在の選択値を取得
        selected_values = set(interaction.data.get("values", []))

        # 選択されたものを追加
        for value in selected_values:
            self.selected_items.add(value)

        # 現在ページにある選択肢のうち、外されたものを削除
        current_page_values = {
            opt.value
            for opt in self.options[
                self.current_page * self.max_items_per_page : (self.current_page + 1) * self.max_items_per_page
            ]
        }
        self.selected_items -= current_page_values - selected_values

        # Embed 更新
        if self.selected_items:
            desc = "\n".join(f"- <@{user_id}>" for user_id in self.selected_items)
        else:
            desc = "（未選択）"

        self.embed.description = desc
        self.embed.set_footer(text=f"ページ: {self.current_page + 1}/{self.total_pages}")

        self.update_menu()
        await interaction.response.edit_message(embed=self.embed, view=self)


# ─────────────────────────
# ページ切り替えボタン
# ─────────────────────────
class PrevPageButton(Button):
    def __init__(self):
        super().__init__(label="前のページ", style=ButtonStyle.gray)

    async def callback(self, interaction: Interaction):
        view = cast(Sleep_Select_Menu, self.view)
        view.current_page -= 1
        view.update_menu()
        view.embed.set_footer(text=f"ページ: {view.current_page + 1}/{view.total_pages}")
        await interaction.response.edit_message(embed=view.embed, view=view)


class NextPageButton(Button):
    def __init__(self):
        super().__init__(label="次のページ", style=ButtonStyle.gray)

    async def callback(self, interaction: Interaction):
        view = cast(Sleep_Select_Menu, self.view)
        view.current_page += 1
        view.update_menu()
        view.embed.set_footer(text=f"ページ: {view.current_page + 1}/{view.total_pages}")
        await interaction.response.edit_message(embed=view.embed, view=view)


# ─────────────────────────
# 選択操作系ボタン
# ─────────────────────────
class SelectAllButton(Button):
    def __init__(self):
        super().__init__(label="すべて選択", style=ButtonStyle.gray)

    async def callback(self, interaction: Interaction):
        view = cast(Sleep_Select_Menu, self.view)

        start = view.current_page * view.max_items_per_page
        end = start + view.max_items_per_page

        for opt in view.options[start:end]:
            view.selected_items.add(opt.value)

        if view.selected_items:
            desc = "\n".join(f"- <@{user_id}>" for user_id in view.selected_items)
        else:
            desc = "（未選択）"

        view.embed.description = desc
        view.update_menu()
        await interaction.response.edit_message(embed=view.embed, view=view)


class ResetSelectionButton(Button):
    def __init__(self):
        super().__init__(label="選択をリセット", style=ButtonStyle.gray)

    async def callback(self, interaction: Interaction):
        view = cast(Sleep_Select_Menu, self.view)

        start = view.current_page * view.max_items_per_page
        end = start + view.max_items_per_page

        for opt in view.options[start:end]:
            view.selected_items.discard(opt.value)

        if view.selected_items:
            desc = "\n".join(f"- <@{user_id}>" for user_id in view.selected_items)
        else:
            desc = "（未選択）"

        view.embed.description = desc
        view.update_menu()
        await interaction.response.edit_message(embed=view.embed, view=view)


class ConfirmButton(Button):
    def __init__(self):
        super().__init__(label="確定", style=discord.ButtonStyle.green)

    async def callback(self, interaction: Interaction):
        view = cast(Sleep_Select_Menu, self.view)
        modal = DisconnectUsersModal(view.selected_items)
        await interaction.response.send_modal(modal)


class DisconnectUsersModal(Modal):
    def __init__(self, selected_users):
        super().__init__(title="寝落ち相手に一言")
        self.selected_users = selected_users
        self.reason_input = discord.ui.TextInput(
            label="一言",
            style=discord.TextStyle.short,
            placeholder="切断相手に向けた一言を記載してください。",
            required=True
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.edit_message(view=None)
        reason = self.reason_input.value
        guild = interaction.guild
        channel = guild.get_channel(MAIN_CHANNELS.S_RECRUIT_CREATE)

        for user_id in self.selected_users:
            member = guild.get_member(int(user_id))
            if member:
                try:
                    thread = await channel.create_thread(
                        name=f"💤Slp-{interaction.user.display_name}",
                        type=discord.ChannelType.private_thread,
                        invitable=False
                    )
                    await thread.send(
                        content=f"<@{interaction.user.id}> <@{member.id}>",
                        embed=VC_Sleep_Response_Embed(user_name=interaction.user.display_name, target_name=member.display_name, comment=reason),
                        silent=True
                        )
                    if member.voice:
                        await member.move_to(None)
                    await asyncio.sleep(1)
                except Exception as e:
                    await interaction.followup.send(f"{member.mention} の処理中にエラーが発生しました: {e}", ephemeral=True)

        await interaction.followup.send("選択したユーザーを切断しました。", ephemeral=True)

class Knock_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_vc_tc_sync = FS_VC_TC_SYNC()
        self.fs_profile = FS_Profile()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        vc: VoiceChannel = interaction.channel

        result = await self.fs_vc_tc_sync.get_from_vc_id(vc.id)

        target = interaction.user

        profile_data = await self.fs_profile.get_profile_data(author_id=target.id)

        if profile_data is not None:
            
            profile_id = profile_data["MESSAGE_ID"]

            if MAIN_ROLES.MALE in [role.id for role in interaction.user.roles]:
                channel_id = MAIN_CHANNELS.PROFILE_MALE
            else:
                channel_id = MAIN_CHANNELS.PROFILE_FEMALE

            profile_url = f"https://discord.com/channels/{MAIN_SERVER_ID}/{channel_id}/{profile_id}"

        else:
            profile_url = "プロフィールが見つかりませんでした。"

        embed = VC_Knock_Receive_Embed(target=target, prof_url=profile_url)
        view = VC_Knock_Receive_View()

        mentions = " ".join(member.mention for member in vc.members)

        if result is None:
            await vc.send(content=mentions, embed=embed, view=view)
        else:
            tc_id = result
            guild = interaction.guild
            tc = guild.get_channel(tc_id) or await guild.fetch_channel(tc_id)

            await tc.send(content=mentions, embed=embed, view=view)

        await interaction.followup.send(embed=VC_Knock_Response_Embed(), ephemeral=True)

class VC_Knock_Receive_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Approve_Button(label="承認", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=0))
        self.add_item(Cancel_Button(label="また今度", emoji=DEFAULT.HAND_PLAY, style=ButtonStyle.gray, row=0))

class Approve_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        vc = interaction.channel
        guild = interaction.guild
        user = interaction.user

        embed = interaction.message.embeds[0]
        target_id = int(embed.author.name)
        target = guild.get_member(target_id) or await guild.fetch_member(target_id)

        overwrite_target = PermissionOverwrite(connect=True, speak=True)

        tc = None

        if isinstance(vc, VoiceChannel):
            pass
        else:
            if user.voice is None or user.voice.channel is None:
                await interaction.edit_original_response(
                    content="❌ ボイスチャンネルに接続していないため、承認できません。",
                    view=None,
                )
                return

            vc = user.voice.channel
            tc = interaction.channel  # エラー時にここで送る

        try:
            await vc.set_permissions(target=target, overwrite=overwrite_target)
        except Exception as e:
            logger.error(f"[Approve_Button] set_permissions failed: {e}", exc_info=True)

            error_embed = System_Error_Embed()

            if tc is None:
                await vc.send(embed=error_embed)
            else:
                await tc.send(embed=error_embed)

            return

        await interaction.edit_original_response(
            content=textwrap.dedent(
                f"""
                -# ✅️ノックを承認しました。
                -# 承認者：{user.display_name} ({user.mention})
                """
            ),
            view=None,
        )

        try:
            await target.send(
                embed=VC_Knock_Approve_DM_Embed(vc_url=vc.jump_url)
            )
        except Exception as e:
            logger.warning(
                f"[Approve_Button] Failed to send DM to user {target.id}: {e}",
                exc_info=True,
            )
            vc.send(content=target.mention, embed=VC_Knock_Approve_Embed())

class Cancel_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):

        guild = interaction.guild

        embed = interaction.message.embeds[0]
        target_id = int(embed.author.name)
        target = guild.get_member(target_id) or await guild.fetch_member(target_id)

        modal = Cancel_Modal(target=target)

        await interaction.response.send_modal(modal)

class Cancel_Modal(Modal):
    def __init__(self, target: User):
        super().__init__(title="また今度", timeout=None)
        self.target = target

        self.comment_input = TextInput(
            label="コメント",
            placeholder="コメントがあればご記入ください。",
            max_length=800,
            style=TextStyle.paragraph,
            required=False
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()

        # 空欄ならデフォルト文をセット
        comment = self.comment_input.value
        if not comment.strip():
            comment = textwrap.dedent(
                '''
                すみません。
                またの機会にお話しましょう。
                '''
            )

        embed = VC_Knock_Cancel_Embed(comment=comment)

        # DM 送信（失敗しても落ちないようにする）
        try:
            await self.target.send(content=f"{self.target.mention}", embed=embed)
        except discord.Forbidden:
            user = interaction.user
            vc = user.voice.channel

            await vc.send(content=f"{self.target.mention}", embed=embed)

        await interaction.edit_original_response(content="🙏 ノックを断りました。", view=None)

        
