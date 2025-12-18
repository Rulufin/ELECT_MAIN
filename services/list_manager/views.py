import discord
from discord.ext import commands, tasks
from discord import (
    app_commands, Interaction,
    SelectOption, TextStyle, ChannelType, ButtonStyle,
    Member, User, Thread, TextChannel, VoiceChannel, ForumChannel
)

from discord.ui import (
    View, Button, Modal, Select,
    TextInput,
    UserSelect, RoleSelect, ChannelSelect
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
from datetime import datetime, timedelta
from typing import Optional, List, Any, Union, Dict
from firestores.fs_recruitments import FS_Number, FS_Recruitments, FS_Rec_Message
from firestores.fs_user_info import FS_Profile
from firestores.fs_list_manager import FS_BlackList, FS_BlackList_From

from utils.ids import *
from utils.emojis import *
from utils.colorcodes import *

from utils.discord.delete_after import delete_after

from services.list_manager.embeds import (
    Waiting_Embed,
    Blacklist_Manage_Embed, List_NotFound_Embed,
    Blacklist_Add_Embed, Blacklist_Add_Check_Embed, Blacklist_Add_Result_Embed,
    Blacklist_Delete_Embed, Blacklist_Delete_Check_Embed, Blacklist_Delete_Result_Embed,
    Blacklist_Check_Embed,
)

FILENAME = "List_Manager"

logger = logging.getLogger(__name__)

TIMEZONE = pytz.timezone("Asia/Tokyo")

class Blacklist_Manage_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Add_Button(label="追加", emoji=DEFAULT.PLUS, style=ButtonStyle.gray, row=0))
        self.add_item(Delete_Button(label="削除", emoji=DEFAULT.TRASH, style=ButtonStyle.gray, row=0))
        self.add_item(Check_Button(label="確認", emoji=DEFAULT.EYES, style=ButtonStyle.gray, row=0))

class Add_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        embed = Blacklist_Add_Embed()
        view = Blacklist_Add_View()

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class Blacklist_Add_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Add_SelectMenu())
        self.add_item(Cancel_Button(label="キャンセル", emoji=DEFAULT.TRASH, style=ButtonStyle.gray, row=1))
    
class Add_SelectMenu(UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="追加するユーザーを選択してください。",
            min_values=1,
            max_values=25,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        # 選択インタラクションは即座に既存メッセージを更新するので defer(ephemeral=True) でOK
        await interaction.response.defer(ephemeral=True)

        # self.values は List[discord.Member | discord.User]
        selected_users = list(self.values)

        # ──────────────────────────────
        # 1. Embed 用の表示リストを作成
        #    1. display_name (mention)
        # ──────────────────────────────
        embed_user_list: list[str] = []
        for idx, user in enumerate(selected_users, start=1):
            display_name = getattr(user, "display_name", getattr(user, "name", "不明ユーザー"))
            line = f"{idx}. {display_name} ({user.mention})"
            embed_user_list.append(line)

        # ──────────────────────────────
        # 2. View 用の「使いやすい形式」のリストを作成
        #    [display_name, user_id] 形式
        # ──────────────────────────────
        view_user_list: list[list[int | str]] = []
        for user in selected_users:
            display_name = getattr(user, "display_name", getattr(user, "name", "不明ユーザー"))
            view_user_list.append([display_name, user.id])

        # Embed / View にそれぞれ渡す
        embed = Blacklist_Add_Check_Embed(user_list=embed_user_list)
        view = Blacklist_Add_Check_View(view_user_list)

        await interaction.edit_original_response(embed=embed, view=view)

class Cancel_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.edit_message(content="キャンセルしました。", embed=None, view=None)

        await delete_after(message=interaction.message, delete_after=5)

class Blacklist_Add_Check_View(View):
    def __init__(self, user_list):
        super().__init__(timeout=None)
        self.add_item(Confirm_Button(label="決定", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=0, btn_type="Add", user_list=user_list))
        self.add_item(Cancel_Button(label="キャンセル", emoji=DEFAULT.TRASH, style=ButtonStyle.gray, row=0))

class Confirm_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type, user_list):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}")
        self.btn_type = btn_type
        self.user_list = user_list
        self.fs_blacklist = FS_BlackList()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        owner = interaction.user

        add_list = []
        add_number = 0
        found_list = []
        found_number = 0
        error_list = []
        error_number = 0
        for user_name, user_id in self.user_list:
            result = await self.fs_blacklist.add_list(
                owner_id=owner.id,
                owner_name=owner.display_name,
                target_id=user_id,
                target_name=user_name
                )
            if result == "ADD":
                add_number += 1
                add_line = f"{add_number}. {user_name} (<@{user_id}>)"
                add_list.append(add_line)
            elif result == "FOUND":
                found_number += 1
                found_line = f"{found_number}. {user_name} (<@{user_id}>)"
                found_list.append(found_line)
            elif result == "ERROR":
                error_number += 1
                line = f"{error_number}. {user_name} (<@{user_id}>)"
                error_list.append(line)
                continue

        embed = Blacklist_Add_Result_Embed(
            add_users=add_list,
            existing_users=found_list,
            error_users=error_list
        )

        await interaction.edit_original_response(embed=embed, view=None)

class Delete_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_Delete_List_Button",
        )
        self.fs_blacklist = FS_BlackList()

    async def callback(self, interaction: discord.Interaction):
        waiting_embed = Waiting_Embed()
        await interaction.response.send_message(embed=waiting_embed, ephemeral=True)

        result = await self.fs_blacklist.get_list(interaction.user.id)

        if result == "NOT_FOUND":
            result_embed = List_NotFound_Embed()
            await interaction.edit_original_response(content=None, embed=result_embed, view=None)
            return

        options = sorted(
            [
                discord.SelectOption(label=entry["name"], value=str(entry["id"]))
                for entry in result
                if "id" in entry and "name" in entry
            ],
            key=lambda option: option.label,
        )

        if not options:
            not_found_embed = List_NotFound_Embed()
            await interaction.edit_original_response(embed=not_found_embed, view=None)
            return

        embed = Blacklist_Delete_Embed()
        view = Delete_List_SelectMenu(options)

        total_pages = (len(options) - 1) // view.max_items_per_page + 1
        content_message = f"ページ: 1/{total_pages}\n現在の選択数: 0個"

        await interaction.edit_original_response(
            content=content_message,
            embed=embed,
            view=view,
        )


class Delete_List_SelectMenu(View):
    def __init__(self, options, max_items_per_page=25):
        super().__init__(timeout=None)
        self.options = options
        self.max_items_per_page = max_items_per_page
        self.current_page = 0
        # {user_id(str): user_name(str)}
        self.selected_items: dict[str, str] = {}
        self.total_pages = (len(self.options) - 1) // self.max_items_per_page + 1
        self.update_menu()

    def update_menu(self):
        """現在のページの選択肢を表示するメニューを更新"""
        start = self.current_page * self.max_items_per_page
        end = start + self.max_items_per_page
        page_options = self.options[start:end]

        # Selectメニューを構築
        if page_options:
            select_menu = Select(
                placeholder="削除するユーザーを選択してください",
                options=[
                    discord.SelectOption(
                        label=opt.label,
                        value=opt.value,
                        default=(opt.value in self.selected_items),  # 選択済みならチェック状態
                    )
                    for opt in page_options
                ],
                max_values=len(page_options),
                min_values=0,
            )
            # コールバックを紐付け
            select_menu.callback = self.select_callback
        else:
            select_menu = None

        # View を再構築
        self.clear_items()
        if select_menu:
            self.add_item(select_menu)

        # ページ移動ボタン
        if self.current_page > 0:
            self.add_item(
                PrevPageButton(
                    label="前のページ",
                    emoji=DEFAULT.PREV,
                    style=discord.ButtonStyle.gray,
                    row=1,
                    parent_view=self,
                )
            )
        if end < len(self.options):
            self.add_item(
                NextPageButton(
                    label="次のページ",
                    emoji=DEFAULT.NEXT,
                    style=discord.ButtonStyle.gray,
                    row=1,
                    parent_view=self,
                )
            )

        # 操作ボタン
        self.add_item(
            SelectAllButton(
                label="このページをすべて選択",
                emoji=DEFAULT.GEAR,
                style=discord.ButtonStyle.gray,
                row=2,
                parent_view=self,
            )
        )
        self.add_item(
            ResetSelectionButton(
                label="このページの選択をリセット",
                emoji=DEFAULT.TRASH,
                style=discord.ButtonStyle.gray,
                row=2,
                parent_view=self,
            )
        )
        self.add_item(
            DeleteConfirmButton(
                label="確定",
                emoji=DEFAULT.CHECK,
                style=discord.ButtonStyle.gray,
                row=3,
                parent_view=self,
            )
        )

    def update_embed(self) -> discord.Embed:
        embed = Blacklist_Delete_Embed()

        if not self.selected_items:
            embed.add_field(
                name="__選択済ユーザー__",
                value="（現在の選択はありません）",
                inline=False,
            )
            return embed

        field_limit = 1024
        fields: list[str] = []
        current_field_lines: list[str] = []
        current_length = 0

        for i, (value, label) in enumerate(self.selected_items.items(), start=1):
            line = f"{i}. {label} (<@{value}>)"
            line_length = len(line) + 1  # 改行込み

            if current_length + line_length > field_limit:
                fields.append("\n".join(current_field_lines))
                current_field_lines = []
                current_length = 0

            current_field_lines.append(line)
            current_length += line_length

        if current_field_lines:
            fields.append("\n".join(current_field_lines))

        for i, field_value in enumerate(fields, start=1):
            embed.add_field(
                name=f"__選択済ユーザー ({i})__",
                value=field_value,
                inline=False,
            )

        return embed

    async def select_callback(self, interaction: discord.Interaction):
        """
        Select の選択変更時に呼ばれるコールバック
        ※ update_menu() 時に select_menu.callback = self.select_callback としている
        """
        selected_values = set(interaction.data.get("values", []))

        # 現在ページの value -> label マップ
        start = self.current_page * self.max_items_per_page
        end = start + self.max_items_per_page
        current_page_options = {
            opt.value: opt.label
            for opt in self.options[start:end]
        }

        # このページの選択状態を更新
        for value, label in current_page_options.items():
            if value in selected_values:
                self.selected_items[value] = label
            else:
                self.selected_items.pop(value, None)

        current_selection_count = len(self.selected_items)
        message_content = (
            f"ページ: {self.current_page + 1}/{self.total_pages}\n"
            f"現在の選択数: {current_selection_count}個"
        )

        self.update_menu()
        embed = self.update_embed()
        await interaction.response.edit_message(
            content=message_content,
            embed=embed,
            view=self,
        )


class PrevPageButton(Button):
    def __init__(self, label, emoji, style, row, parent_view: Delete_List_SelectMenu):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self._parent_view.current_page -= 1
        self._parent_view.update_menu()

        message_content = (
            f"ページ: {self._parent_view.current_page + 1}/{self._parent_view.total_pages}\n"
            f"現在の選択数: {len(self._parent_view.selected_items)}個"
        )
        embed = self._parent_view.update_embed()
        await interaction.response.edit_message(
            content=message_content,
            embed=embed,
            view=self._parent_view,
        )


class NextPageButton(Button):
    def __init__(self, label, emoji, style, row, parent_view: Delete_List_SelectMenu):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self._parent_view.current_page += 1
        self._parent_view.update_menu()

        message_content = (
            f"ページ: {self._parent_view.current_page + 1}/{self._parent_view.total_pages}\n"
            f"現在の選択数: {len(self._parent_view.selected_items)}個"
        )
        embed = self._parent_view.update_embed()
        await interaction.response.edit_message(
            content=message_content,
            embed=embed,
            view=self._parent_view,
        )


class SelectAllButton(Button):
    def __init__(self, label, emoji, style, row, parent_view: Delete_List_SelectMenu):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        """現在のページのすべての項目を選択"""
        start = self._parent_view.current_page * self._parent_view.max_items_per_page
        end = start + self._parent_view.max_items_per_page
        current_page_options = self._parent_view.options[start:end]

        for opt in current_page_options:
            # dict に {id: name} として保持
            self._parent_view.selected_items[opt.value] = opt.label

        current_selection_count = len(self._parent_view.selected_items)
        message_content = (
            f"ページ: {self._parent_view.current_page + 1}/{self._parent_view.total_pages}\n"
            f"現在の選択数: {current_selection_count}個"
        )

        self._parent_view.update_menu()
        embed = self._parent_view.update_embed()
        await interaction.response.edit_message(
            content=message_content,
            embed=embed,
            view=self._parent_view,
        )


class ResetSelectionButton(Button):
    def __init__(self, label, emoji, style, row, parent_view: Delete_List_SelectMenu):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        """現在のページの選択をリセット"""
        start = self._parent_view.current_page * self._parent_view.max_items_per_page
        end = start + self._parent_view.max_items_per_page
        current_page_options = self._parent_view.options[start:end]

        for opt in current_page_options:
            self._parent_view.selected_items.pop(opt.value, None)

        current_selection_count = len(self._parent_view.selected_items)
        message_content = (
            f"ページ: {self._parent_view.current_page + 1}/{self._parent_view.total_pages}\n"
            f"現在の選択数: {current_selection_count}個"
        )

        self._parent_view.update_menu()
        embed = self._parent_view.update_embed()
        await interaction.response.edit_message(
            content=message_content,
            embed=embed,
            view=self._parent_view,
        )


class DeleteConfirmButton(Button):
    def __init__(self, label, emoji, style, row, parent_view: Delete_List_SelectMenu):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._parent_view = parent_view
        self.fs_blacklist = FS_BlackList()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        delete_list: list[tuple[str, str]] = []  # (label, id)
        error_list: list[tuple[str, str]] = []

        for value, label in self._parent_view.selected_items.items():
            try:
                # FS_BlackList 側が str 受け取り想定なので str 化して渡す
                result = await self.fs_blacklist.remove_list(str(interaction.user.id), str(value))
                if result == "REMOVED":
                    delete_list.append((label, value))
                else:
                    error_list.append((label, value))
            except Exception:
                error_list.append((label, value))

        embed = Blacklist_Delete_Result_Embed(
            add_users="\n".join(
                f"{i+1}. {label} (<@{value}>)"
                for i, (label, value) in enumerate(delete_list)
            ),
            error_users="\n".join(
                f"{i+1}. {label} (<@{value}>)"
                for i, (label, value) in enumerate(error_list)
            ),
        )

        await interaction.edit_original_response(content=None, embed=embed, view=None)
        self._parent_view.stop()


MAX_FIELD_VALUE = 1024      # 1フィールドの最大文字数
MAX_FIELDS_PER_EMBED = 3    # 1Embedに持たせるフィールド数の上限

def build_lines_from_entries(entries: List[Dict[str, Any]]) -> List[str]:
    """
    [{id, name}, ...] から '1. name (<@id>)' 形式の行リストを作る
    """
    lines: List[str] = []
    for idx, entry in enumerate(entries, start=1):
        user_id = entry.get("id")
        name = entry.get("name", "Unknown")
        lines.append(f"{idx}. {name} (<@{user_id}>)")
    return lines


def chunk_lines(lines: List[str], max_len: int = MAX_FIELD_VALUE) -> List[str]:
    """
    行リストを、max_len 以内の文字列チャンクに分割する。
    各チャンクは「改行連結済みの文字列」になる。
    """
    chunks: List[str] = []
    buf: List[str] = []
    current_len = 0

    for line in lines:
        line_text = line + "\n"
        line_len = len(line_text)

        # 今のバッファに追加すると上限超えるなら、新チャンクを開始
        if buf and current_len + line_len > max_len:
            chunks.append("".join(buf).rstrip("\n"))
            buf = []
            current_len = 0

        buf.append(line_text)
        current_len += line_len

    if buf:
        chunks.append("".join(buf).rstrip("\n"))

    return chunks


def build_blacklist_embeds_from_chunks(chunks: List[str]) -> List[discord.Embed]:
    """
    文字列チャンク（各 <= 1024）を元に複数 Embed を生成する。
    1Embedあたり最大3フィールド。それを超えたら次のEmbed（＝次のメッセージ用）。
    """
    if not chunks:
        # 空の場合は「登録なし」Embedを返す想定なら、
        # ここで専用Embedを返してもOK（List_NotFound_Embedでも良い）
        embed = discord.Embed(
            title="__ブラックリスト - 確認__",
            description="現在登録されているユーザーはいません。"
        )
        return [embed]

    embeds: List[discord.Embed] = []
    total_chunks = len(chunks)

    chunk_index = 0
    page = 1

    while chunk_index < total_chunks:
        embed = discord.Embed(
            title="__ブラックリスト - 確認__",
            description="現在の登録状況。"
        )

        fields_in_this_embed = 0
        while chunk_index < total_chunks and fields_in_this_embed < MAX_FIELDS_PER_EMBED:
            value = chunks[chunk_index]
            name = "__一覧__" if (page == 1 and fields_in_this_embed == 0) else "__一覧（続き）__"
            embed.add_field(name=name, value=value, inline=False)

            chunk_index += 1
            fields_in_this_embed += 1

        embed.set_footer(text=f"ページ {page}")
        page += 1
        embeds.append(embed)

    return embeds


class Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )
        from firestores.fs_list_manager import FS_BlackList
        self.fs_blacklist = FS_BlackList()

    async def callback(self, interaction: Interaction):
        owner = interaction.user

        # まず queue 経由でデータ取得
        entries = await self.fs_blacklist.get_list(owner.id)

        if entries == "NOT_FOUND" or not entries:
            # 登録なし
            embed = List_NotFound_Embed()
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 1. 行を作成
        lines = build_lines_from_entries(entries)

        # 2. 行を1024文字以内のチャンクに分割
        chunks = chunk_lines(lines)

        # 3. チャンクから複数Embedを構築（1Embed = 最大3フィールド）
        embeds = build_blacklist_embeds_from_chunks(chunks)

        # 4. メッセージ送信
        #   - 各メッセージに1Embedだけ乗せる
        first_embed = embeds[0]
        await interaction.response.send_message(embed=first_embed, ephemeral=True)

        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed, ephemeral=True)

        