import discord
from discord.ext import commands, tasks
from discord import (
    app_commands, Interaction,
    SelectOption, TextStyle, ChannelType, ButtonStyle,
    Member, User, Thread, TextChannel, VoiceChannel, ForumChannel, Guild
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
from datetime import datetime, timedelta
from typing import Optional

from firestores.fs_recruitments import FS_Number, FS_Recruitments, FS_Rec_Message
from firestores.fs_user_info import FS_Profile
from firestores.fs_list_manager import FS_BlackList, FS_BlackList_From

from utils.ids import *
from utils.emojis import *
from utils.colorcodes import *
from services.recruit.ui.embeds import *
from services.system.embeds import System_Profile_NotFoud_Embed, System_Error_Embed

from utils.discord.helpers.latelimit import check_button_cooldown

FILENAME = "Secret_Recruit"

logger = logging.getLogger(__name__)

TIMEZONE = pytz.timezone("Asia/Tokyo")

OP_AGE = [
    SelectOption(label="20代前半", value=f"<@&{MAIN_ROLES.AGE_TWENTY_BEFORE}>"),
    SelectOption(label="20代後半", value=f"<@&{MAIN_ROLES.AGE_TWENTY_AFTER}>"),
    SelectOption(label="30代前半", value=f"<@&{MAIN_ROLES.AGE_THIRTY_BEFORE}>"),
    SelectOption(label="30代後半", value=f"<@&{MAIN_ROLES.AGE_THIRTY_AFTER}>"),
    SelectOption(label="40代前半", value=f"<@&{MAIN_ROLES.AGE_FOURTY_BEFORE}>"),
    SelectOption(label="40代後半", value=f"<@&{MAIN_ROLES.AGE_FOURTY_AFTER}>"),
    SelectOption(label="50代以上", value=f"<@&{MAIN_ROLES.AGE_FIFTY_OVER}>"),
]

OP_VOICE = [
    SelectOption(label="高音", value=f"<@&{MAIN_ROLES.VO_HIGH}>"),
    SelectOption(label="中高音", value=f"<@&{MAIN_ROLES.VO_MIDHIGH}>"),
    SelectOption(label="中音", value=f"<@&{MAIN_ROLES.VO_MID}>"),
    SelectOption(label="中低音", value=f"<@&{MAIN_ROLES.VO_MIDLOW}>"),
    SelectOption(label="低音", value=f"<@&{MAIN_ROLES.VO_LOW}>"),
]

OP_TYPE = [
    SelectOption(label="ドM", value=f"<@&{MAIN_ROLES.MASOCHIST_HEAVY}>"),
    SelectOption(label="M", value=f"<@&{MAIN_ROLES.MASOCHIST_LIGHT}>"),
    SelectOption(label="S", value=f"<@&{MAIN_ROLES.SADIST_LIGHT}>"),
    SelectOption(label="ドS", value=f"<@&{MAIN_ROLES.SADIST_HEAVY}>"),
    SelectOption(label="ドミ", value=f"<@&{MAIN_ROLES.DOMINANT}>"),
    SelectOption(label="サブ", value=f"<@&{MAIN_ROLES.SUBMISSIVE}>"),
    SelectOption(label="スイッチャー", value=f"<@&{MAIN_ROLES.SWITCHER}>"),
]

OP_STYLE = [
    SelectOption(label="疑似", value=f"<@&{MAIN_ROLES.PSEUDO_SEX}>"),
    SelectOption(label="指示", value=f"<@&{MAIN_ROLES.INSTRUCTION}>"),
    SelectOption(label="相互", value=f"<@&{MAIN_ROLES.MUTUAL}>"),
    SelectOption(label="ソロオナ", value=f"<@&{MAIN_ROLES.SOLO}>"),

    SelectOption(label="いちゃ甘", value=f"<@&{MAIN_ROLES.ICHA_AMA}>"),
    SelectOption(label="いちゃボコ", value=f"<@&{MAIN_ROLES.ICHA_BOKO}>"),
    SelectOption(label="バチボコ", value=f"<@&{MAIN_ROLES.BACHI_BOKO}>"),

    SelectOption(label="サクエロ", value=f"<@&{MAIN_ROLES.SAKU_ERO}>"),
    SelectOption(label="すり合わせ必須", value=f"<@&{MAIN_ROLES.SURIAWASE}>"),
]

OP_SELECT = [
    SelectOption(label="年齢", value="年齢"),
    SelectOption(label="声質", value="声質"),
    SelectOption(label="属性", value="属性"),
    SelectOption(label="プレイスタイル", value="プレイスタイル")
]

class Recruit_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Recruit_Create_Button(label="記名募集", emoji=None, style=discord.ButtonStyle.gray, row=0, btn_type="Signed"))
        self.add_item(Recruit_Create_Button(label="匿名募集", emoji=None, style=discord.ButtonStyle.gray, row=0, btn_type="Anonymous"))

class Recruit_Create_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}")
        self.btn_type = btn_type
        self.fs_number = FS_Number()
        self.fs_profile = FS_Profile()

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()

        user = interaction.user
        channel = interaction.channel

        # スレッド名: "マイページ-ユーザーID"
        thread_name = f"{DEFAULT.PIN}R-{user.id}"

        # 既存のスレッドを検索（アクティブ + アーカイブ済み）
        existing_thread: Thread = await self.find_existing_thread(channel, thread_name)

        if existing_thread:
            # 既存スレッドが見つかった場合、ジャンプURLを送信
            message = await existing_thread.send(f"<@{interaction.user.id}>")
            await asyncio.sleep(0.5)
            await message.delete()

            await interaction.followup.send(
                content=f"既に裏募集が存在します: {existing_thread.jump_url}",
                ephemeral=True
            )
            return
        else:
            profile_data = await self.fs_profile.get_profile_data(interaction.user.id)

            if profile_data is None or profile_data == "NOT_FOUND":
                await interaction.followup.send(embed=System_Profile_NotFoud_Embed(), ephemeral=True)
                return
            
            profile_id = profile_data["MESSAGE_ID"]

            if MAIN_ROLES.MALE in [role.id for role in interaction.user.roles]:
                color = SERVER_COLORS.MALE
                channel_id = MAIN_CHANNELS.PROFILE_MALE
                gender_role_id = MAIN_ROLES.FEMALE
            else:
                color = SERVER_COLORS.FEMALE
                channel_id = MAIN_CHANNELS.PROFILE_FEMALE
                gender_role_id = MAIN_ROLES.MALE

            profile_url = f"https://discord.com/channels/{MAIN_SERVER_ID}/{channel_id}/{profile_id}"

            current_number = await self.fs_number.get_number()

            if current_number == "ERROR":
                await interaction.followup.send(embed=System_Error_Embed(), ephemeral=True)
                return

            if self.btn_type == "Signed":
                main_embed = Recruit_Signed_Setting_Embed(
                    user_name = interaction.user.display_name,
                    user_id = interaction.user.id,
                    user_avatar_url = interaction.user.display_avatar.url,
                    profile_url = profile_url,
                    color = color,
                    number = current_number
                )
            elif self.btn_type == "Anonymous":
                main_embed = Recruit_Anonymous_Setting_Embed(
                    color = color,
                    number = current_number
                )

            sub_embed = Recruit_Other_Setting_Embed(
                role_id = gender_role_id
            )

            # 新しいスレッドを作成
            new_thread = await channel.create_thread(
                name=thread_name,
                type=ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=1440
            )

            setting_message = await new_thread.send(
                content=f"<@{interaction.user.id}>",
                embeds=[main_embed, sub_embed],
                view=Recruit_Main_Setting_View()
            )

            await new_thread.send(
                embed=Recruit_Post_Embed(setting_message.id),
                view=Recruit_Post_View()
            )

            await interaction.followup.send(embed=Create_Thread_Embed(channel_id=new_thread.id), ephemeral=True)

    async def find_existing_thread(self, channel: TextChannel, thread_name):
        """
        指定した `channel` 内で `thread_name` に一致するスレッドを検索する。
        - アクティブなスレッド
        - アーカイブ済みスレッド（公開 & 非公開）
        の両方を対象にする。
        """
        # まず、アクティブなスレッドを検索
        existing_thread = get(channel.threads, name=thread_name)

        if existing_thread:
            return existing_thread  # アクティブなスレッドが見つかったら返す

        # 見つからなければ、アーカイブされたスレッド（公開）を取得して検索
        async for thread in channel.archived_threads(limit=None, private=False):
            if thread.name == thread_name:
                return thread  # 公開アーカイブスレッドが見つかったら返す

        # プライベートスレッドも取得して検索
        async for thread in channel.archived_threads(limit=None, private=True):
            if thread.name == thread_name:
                return thread  # 非公開アーカイブスレッドが見つかったら返す

        return None  # どこにもスレッドが存在しない場合

class Recruit_Main_Setting_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Content_Set_Button(label="内容設定", emoji=DEFAULT.MEMO, style=discord.ButtonStyle.gray, row=0))
        self.add_item(Filter_Set_Button(label="ロール設定", emoji=DEFAULT.GEAR, style=discord.ButtonStyle.gray, row=0))

class Content_Set_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        main_embed = interaction.message.embeds[0]

        default_input = {}

        if main_embed.title == "__記名裏募集__":
            for field in main_embed.fields:
                if field.name in ["__したいこと__", "__いつから__", "__相手に望むもの__", "__一言__"]:
                    key = field.name.strip("_")  # "__したいこと__" → "したいこと"
                    default_input[key] = field.value
            modal = Signed_Content_Set_Modal(
                message_id = interaction.message.id,
                default_input = default_input
                )
        else:
            for field in main_embed.fields:
                if field.name in ["__募集者のヒント__", "__したいこと__", "__いつから__", "__相手に望むもの__", "__一言__"]:
                    key = field.name.strip("_")
                    default_input[key] = field.value
            modal = Anonymous_Content_Set_Modal(
                message_id = interaction.message.id,
                default_input = default_input
                )

        await interaction.response.send_modal(modal)

class Signed_Content_Set_Modal(Modal):
    def __init__(self, message_id, default_input):
        super().__init__(title="記名裏募集 - 内容設定")
        self.message_id = message_id
        self.content_input = TextInput(
            label="したいこと",
            style=TextStyle.short,
            placeholder="雑談、猥談、作業、ゲーム、エロイプ、寝落ち、他",
            default=f'{default_input["したいこと"]}',
            required=True
        )
        self.time_input = TextInput(
            label="いつから",
            style=TextStyle.short,
            placeholder="いまから、◯時から、など",
            default=f'{default_input["いつから"]}',
            required=True
        )
        self.your_input = TextInput(
            label="相手に望むもの(任意)",
            style=TextStyle.paragraph,
            placeholder="相手に望むものを好きに記入してください",
            default=f'{default_input["相手に望むもの"]}',
            required=True
        )
        self.comment_input = TextInput(
            label="一言",
            style=TextStyle.paragraph,
            placeholder="お好きに記入してください",
            default=f'{default_input["一言"]}',
            required=True
        )
        self.add_item(self.content_input)
        self.add_item(self.time_input)
        self.add_item(self.your_input)
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()

        setting_message = await interaction.channel.fetch_message(self.message_id)
        main_embed = setting_message.embeds[0]
        other_embed = setting_message.embeds[1]

        # Embed を JSON 形式に変換
        embed_dict = main_embed.to_dict()

        # フィールドを更新
        for field in embed_dict["fields"]:
            if field["name"] == "__したいこと__":
                field["value"] = self.content_input.value
            elif field["name"] == "__いつから__":
                field["value"] = self.time_input.value
            elif field["name"] == "__相手に望むもの__":
                field["value"] = self.your_input.value
            elif field["name"] == "__一言__":
                field["value"] = self.comment_input.value

        # JSON から新しい Embed を作成
        new_main_embed = discord.Embed.from_dict(embed_dict)

        await interaction.edit_original_response(embeds=[new_main_embed, other_embed])

class Anonymous_Content_Set_Modal(Modal):
    def __init__(self, message_id, default_input):
        super().__init__(title="匿名裏募集 - 内容設定")
        self.message_id = message_id
        self.hint_input = TextInput(
            label="募集者のヒント",
            style=TextStyle.short,
            placeholder="お好きに記入してください",
            default=f'{default_input["募集者のヒント"]}',
            required=True
        )
        self.content_input = TextInput(
            label="したいこと",
            style=TextStyle.short,
            placeholder="雑談、猥談、作業、ゲーム、エロイプ、寝落ち、他",
            default=f'{default_input["したいこと"]}',
            required=True
        )
        self.time_input = TextInput(
            label="いつから",
            style=TextStyle.short,
            placeholder="いまから、◯時から、など",
            default=f'{default_input["いつから"]}',
            required=True
        )
        self.your_input = TextInput(
            label="相手に望むもの(任意)",
            style=TextStyle.paragraph,
            placeholder="お好きに記入してください",
            default=f'{default_input["相手に望むもの"]}',
            required=True
        )
        self.comment_input = TextInput(
            label="一言",
            style=TextStyle.paragraph,
            placeholder="お好きに記入してください",
            default=f'{default_input["一言"]}',
            required=True
        )
        self.add_item(self.hint_input)
        self.add_item(self.content_input)
        self.add_item(self.time_input)
        self.add_item(self.your_input)
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()

        setting_message = await interaction.channel.fetch_message(self.message_id)
        main_embed = setting_message.embeds[0]
        other_embed = setting_message.embeds[1]

        # Embed を JSON 形式に変換
        embed_dict = main_embed.to_dict()

        # フィールドを更新
        for field in embed_dict["fields"]:
            if field["name"] == "__募集者のヒント__":
                field["value"] = self.hint_input.value
            elif field["name"] == "__したいこと__":
                field["value"] = self.content_input.value
            elif field["name"] == "__いつから__":
                field["value"] = self.time_input.value
            elif field["name"] == "__相手に望むもの__":
                field["value"] = self.your_input.value
            elif field["name"] == "__一言__":
                field["value"] = self.comment_input.value

        # JSON から新しい Embed を作成
        new_main_embed = Embed.from_dict(embed_dict)

        await interaction.edit_original_response(embeds=[new_main_embed, other_embed])

class Filter_Set_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()

        sub_embed = interaction.message.embeds[1]
        
        for field in sub_embed.fields:
            if field.name == "__性別__":
                gender_role = field.value
            elif field.name == "__その他ロール__":
                filter_roles = field.value
        
        embed = Recruit_Filter_Set_Embed(message_id = interaction.message.id, gender_role=gender_role, filter_roles=filter_roles)

        view = Recruit_Filter_Panel_View()

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

class Recruit_Filter_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Filter_Setting_Button(label="設定", emoji=DEFAULT.GEAR, style=ButtonStyle.gray, row=0))
        self.add_item(Filter_Reset_Button(label="リセット", emoji=DEFAULT.RESET, style=ButtonStyle.gray, row=0))
        self.add_item(Filter_Check_Button(label="確認", emoji=DEFAULT.EYES, style=ButtonStyle.gray, row=0))
        self.add_item(Filter_Confirm_Button(label="確定", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=1))

class Filter_Setting_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
    
    async def callback(self, interaction: Interaction):
        await interaction.response.edit_message(view=Recruit_Filter_Setting_View())

class Recruit_Filter_Setting_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Filter_Option_Select_Menu())

class Filter_Option_Select_Menu(Select):
    def __init__(self):
        super().__init__(placeholder="設定したい項目を選択してください。", options=OP_SELECT, min_values=1, max_values=1, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()

        filter_embed = interaction.message.embeds[0]
        selected_roles = []
        for field in filter_embed.fields:
            if field.name == "__その他ロール__":
                selected_roles = field.value.split(" ")

        view = Filter_Role_Select_View(self.values[0], selected_roles)

        await interaction.edit_original_response(view=view)

class Filter_Role_Select_View(View):
    def __init__(self, select_type, selected_roles):
        super().__init__(timeout=None)
        self.add_item(Filter_Role_Select_Menu(select_type, selected_roles))

class Filter_Role_Select_Menu(Select):
    def __init__(self, select_type, selected_roles):
        select_map = {
            "年齢": OP_AGE,
            "声質": OP_VOICE,
            "属性": OP_TYPE,
            "プレイスタイル": OP_STYLE
        }
        options = select_map.get(select_type, [])

        # その他ロールが空なら selected_roles も空にする
        if not selected_roles:
            selected_roles = set()  # 空のセットにする

        # デフォルト選択済みのオプションを適切に設定
        for option in options:
            option.default = option.value in selected_roles  # selected_roles に含まれるものだけ default にする

        super().__init__(
            placeholder="設定したいロールを選択してください。",
            options=options,
            min_values=0,  # 未選択を許可
            max_values=len(options),
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )
        self.select_type = select_type
        self.selected_roles = selected_roles

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()
        filter_embed = interaction.message.embeds[0]
        filter_dict = filter_embed.to_dict()

        # 既存のロールリストを取得（<@&ID> 形式）
        current_roles = set()
        for field in filter_dict["fields"]:
            if field["name"] == "__その他ロール__":
                current_roles = set(field["value"].split(" "))  # スペース区切りでリスト化

        # 現在の選択肢（options の中身）を取得
        selectable_roles = {option.value for option in self.options}

        # 追加すべきロール（self.values に入っているもの）
        selected_roles = set(self.values)

        # 更新後のロールリスト作成
        updated_roles = (current_roles - selectable_roles) | selected_roles

        # 更新後のフィールドを設定
        for field in filter_dict["fields"]:
            if field["name"] == "__その他ロール__":
                field["value"] = " ".join(updated_roles) if updated_roles else ""

        new_filter_embed = Embed.from_dict(filter_dict)
        await interaction.edit_original_response(embed=new_filter_embed, view=Recruit_Filter_Panel_View())

class Filter_Reset_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        filter_embed = interaction.message.embeds[0]
        filter_dict = filter_embed.to_dict()

        for field in filter_dict["fields"]:
            if field["name"] == "__その他ロール__":
                field["value"] = ""

        new_filter_embed = Embed.from_dict(filter_dict)

        await interaction.response.edit_message(embed=new_filter_embed)

class Filter_Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("メンバー情報を取得中です... 少々お待ちください。", ephemeral=True)

        filter_embed = interaction.message.embeds[0]
        filter_dict = filter_embed.to_dict()

        current_roles = set()
        for field in filter_dict["fields"]:
            role_ids = re.findall(r"<@&(\d+)>", field["value"])
            current_roles.update(int(role_id) for role_id in role_ids)

        guild = interaction.guild
        all_members = list(guild.members)

        # キャッシュが不足している場合はfetchで補完
        approx_member_count = guild.approximate_member_count
        if approx_member_count is None or len(all_members) < approx_member_count:
            all_members = [member async for member in guild.fetch_members(limit=None)]

        target_members = [
            member for member in all_members
            if set(current_roles).issubset({role.id for role in member.roles})
        ]

        total_members = len(target_members)


        member_embed = Embed(
            description=f"対象メンバー数: {total_members}人"
        )

        await interaction.edit_original_response(content=None, embed=member_embed)

class Filter_Confirm_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await interaction.response.edit_message(content="設定を反映します。", embed=None, view=None, delete_after=5)

        filter_embed = interaction.message.embeds[0]
        filter_dict = filter_embed.to_dict()

        for field in filter_dict["fields"]:
            if field["name"] == "__その他ロール__":
                filter_roles = field["value"]

        message_id = int(filter_dict["author"]["name"])
        message = await interaction.channel.fetch_message(message_id)

        main_embed = message.embeds[0]
        sub_embed = message.embeds[1]

        sub_dict = sub_embed.to_dict()

        for field in sub_dict["fields"]:
            if field["name"] == "__その他ロール__":
                field["value"] = filter_roles

        new_sub_embed = discord.Embed.from_dict(sub_dict)

        await message.edit(embeds=[main_embed, new_sub_embed])

class Recruit_Post_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Post_Button(label="公開", emoji=DEFAULT.MALE_HEART, style=discord.ButtonStyle.gray, row=0))
        self.add_item(Edit_Button(label="編集", emoji=DEFAULT.GEAR, style=discord.ButtonStyle.gray, row=0))
        self.add_item(Delete_Button(label="削除", emoji=DEFAULT.TRASH, style=discord.ButtonStyle.gray, row=0))

class Post_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_recruitments = FS_Recruitments()
        self.fs_blacklist = FS_BlackList()
        self.fs_blacklist_from = FS_BlackList_From()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("裏募集を公開します。", ephemeral=True)

        check = await self.fs_recruitments.check_data(interaction.user.id)

        if check == "FOUND":
            await interaction.edit_original_response(content=None, embed=Recruit_FoundData_Embed())
            return
        
        guild = interaction.guild
        owner_id = interaction.user.id
        post_embed = interaction.message.embeds[0]
        setting_message = await interaction.channel.fetch_message(int(post_embed.author.name))
        main_embed, sub_embed = setting_message.embeds[0], setting_message.embeds[1]

        main_dict, sub_dict = main_embed.to_dict(), sub_embed.to_dict()

        anonymity = "Signed" if main_dict["title"] == "__記名裏募集__" else "Anonymous"

        field_map = {
            "__募集主__": "owner_info",
            "__プロフィール__": "profile_url",
            "__募集者のヒント__": "hint",
            "__したいこと__": "content",
            "__いつから__": "desire_time",
            "__相手に望むもの__": "desire_you",
            "__一言__": "message"
        }
        extracted_data = {field_map[field["name"]]: field["value"] for field in main_dict["fields"] if field["name"] in field_map}

        gender_role, filter_roles = None, []

        for field in sub_dict["fields"]:
            if field["name"] == "__性別__":
                gender_role = field["value"]
            elif field["name"] == "__その他ロール__":
                # 空の値を除外
                filter_roles = [role for role in field["value"].split(" ") if role]

        now = datetime.now(TIMEZONE)
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")

        logger.debug(f"gender_role: {gender_role}\nfilter_roles: {filter_roles}")

        allowed_users = {
            member.id for member in guild.members
            if gender_role in {f'<@&{role.id}>' for role in member.roles} and
            (not filter_roles or all(role in {f'<@&{role.id}>' for role in member.roles} for role in filter_roles))
        }

        logger.debug(f"allowed_users: {allowed_users}")


        blacklist, blacklist_from = await self.blacklist_get(owner_id)
        
        # "NOT_FOUND" の場合は空リストにする
        blacklist = [] if blacklist == "NOT_FOUND" else blacklist
        blacklist_from = [] if blacklist_from == "NOT_FOUND" else blacklist_from

        logger.debug(f"blacklist: {blacklist}\nblacklist_from: {blacklist_from}")

        # IDのみ取得
        blacklist_ids = {int(entry["id"]) for entry in blacklist if isinstance(entry, dict)}
        logger.debug(f"blacklist_ids: {blacklist_ids}")
        blacklist_from_ids = {int(entry["id"]) for entry in blacklist_from if isinstance(entry, dict)}
        logger.debug(f"blacklist_ids: {blacklist_from_ids}")

        filtered_users = [str(user) for user in allowed_users if user not in blacklist_ids and user not in blacklist_from_ids]

        data = {
            "Message_ID": main_dict["footer"].get("text", ""),
            "Thread_ID": str(interaction.channel.id),
            "Content": extracted_data["content"],
            "Desire_Time": extracted_data["desire_time"],
            "Desire_You": extracted_data["desire_you"],
            "Message": extracted_data["message"],
            "Target_Role": f"{gender_role} {' '.join(filter_roles)}",
            "Posted_Time": current_time,
            "Anonymity": anonymity,
            "Allowed_Users": filtered_users
        }

        if anonymity == "Signed":
            data.update({
                "Owner_Info": extracted_data["owner_info"],
                "Profile_url": extracted_data["profile_url"],
            })
        else:
            data.update({
                "Hint": extracted_data["hint"],
            })

        result = await self.fs_recruitments.add_recruit_data(owner_id=owner_id, data=data)

        if result == "ERROR":
            await interaction.edit_original_response(content=None, embed=System_Error_Embed())
        else:
            await interaction.edit_original_response(content="裏募集を公開しました。")

        await self.notification(guild=guild, gender_role=gender_role, filtered_users=filtered_users, anonymity=anonymity)

    async def blacklist_get(self, owner_id):
        blacklist = await self.fs_blacklist.get_list(owner_id=owner_id)
        blacklist_from = await self.fs_blacklist_from.get_list(owner_id=owner_id)
        return blacklist, blacklist_from
    
    async def notification(self, guild: Guild, gender_role, filtered_users, anonymity):
        logger.debug(f"filtered_users: {filtered_users}")

        now = datetime.now(TIMEZONE)

        if gender_role == f"<@&{MAIN_ROLES.MALE}>":
            channel_id = MAIN_CHANNELS.S_RECRUIT_MALE
        else:
            channel_id = MAIN_CHANNELS.S_RECRUIT_FEMALE

        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)

        if not channel:
            return

        if anonymity == "Signed":
            recruit_role_id = MAIN_ROLES.RECRUIT_MN_SIGNED if 0 <= now.hour < 6 else MAIN_ROLES.RECRUIT_SIGNED
        else:
            recruit_role_id = MAIN_ROLES.RECRUIT_MN_ANONY if 0 <= now.hour < 6 else MAIN_ROLES.RECRUIT_ANONY

        # ギルドのメンバー情報を取得 (キーを `str` に変換)
        members = {str(member.id): member for member in guild.members}

        # `filtered_users` の中から `recruit_role_id` を持っているユーザーのみを抽出
        target_users = [
            user_id for user_id in filtered_users
            if user_id in members and any(role.id == recruit_role_id for role in members[user_id].roles)
        ]

        logger.debug(f"target_users: {target_users}")

        mention_chunks = []
        chunk = ""
        for user_id in target_users:
            mention = f"<@{user_id}>"
            if len(chunk) + len(mention) > 1900:  # Discord のメッセージ制限 2000 文字に余裕を持たせる
                mention_chunks.append(chunk)
                chunk = ""
            chunk += mention + " "
        if chunk:
            mention_chunks.append(chunk)

        for mention_text in mention_chunks:
            message = await channel.send(mention_text)  # 送信したメッセージを取得
            await asyncio.sleep(0.25)
            await message.delete()

        # `.edit()` を行うためにダミーメッセージを最後に送信して編集
        last_message = await channel.send(".")
        await last_message.edit(content=f"<@&{recruit_role_id}>", embed=Recruit_New_Info_Embed(anonymity))

class Edit_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_recruitments = FS_Recruitments()
        self.fs_blacklist = FS_BlackList()
        self.fs_blacklist_from = FS_BlackList_From()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("裏募集を編集します。", ephemeral=True)

        check = await self.fs_recruitments.check_data(interaction.user.id)

        if check != "FOUND":
            await interaction.edit_original_response(content=None, embed=Recruit_NotFoundData_Embed())
            return
        
        guild = interaction.guild
        owner_id = interaction.user.id
        post_embed = interaction.message.embeds[0]
        setting_message = await interaction.channel.fetch_message(int(post_embed.author.name))
        main_embed, sub_embed = setting_message.embeds[0], setting_message.embeds[1]

        main_dict, sub_dict = main_embed.to_dict(), sub_embed.to_dict()

        anonymity = "Signed" if main_dict["title"] == "__記名裏募集__" else "Anonymous"

        field_map = {
            "__募集主__": "owner_info",
            "__プロフィール__": "profile_url",
            "__募集者のヒント__": "hint",
            "__したいこと__": "content",
            "__いつから__": "desire_time",
            "__相手に望むもの__": "desire_you",
            "__一言__": "message"
        }
        extracted_data = {field_map[field["name"]]: field["value"] for field in main_dict["fields"] if field["name"] in field_map}

        gender_role, filter_roles = None, []
        for field in sub_dict["fields"]:
            if field["name"] == "__性別__":
                gender_role = field["value"]
            elif field["name"] == "__その他ロール__":
                filter_roles = field["value"].split(" ")

        now = datetime.now(TIMEZONE)
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")

        allowed_users = {
            member.id for member in guild.members
            if gender_role in {f'<@&{role.id}>' for role in member.roles} and
            (not filter_roles or all(role in {f'<@&{role.id}>' for role in member.roles} for role in filter_roles))
        }

        blacklist, blacklist_from = await self.blacklist_get(owner_id)
        
        # "NOT_FOUND" の場合は空リストにする
        blacklist = [] if blacklist == "NOT_FOUND" else blacklist
        blacklist_from = [] if blacklist_from == "NOT_FOUND" else blacklist_from

        logger.debug(f"blacklist: {blacklist}\nblacklist_from: {blacklist_from}")

        # IDのみ取得
        blacklist_ids = {int(entry["id"]) for entry in blacklist if isinstance(entry, dict)}
        blacklist_from_ids = {int(entry["id"]) for entry in blacklist_from if isinstance(entry, dict)}

        filtered_users = [str(user) for user in allowed_users if user not in blacklist_ids and user not in blacklist_from_ids]

        data = {
            "Message_ID": main_dict["footer"].get("text", ""),
            "Thread_ID": str(interaction.channel.id),
            "Content": extracted_data["content"],
            "Desire_Time": extracted_data["desire_time"],
            "Desire_You": extracted_data["desire_you"],
            "Message": extracted_data["message"],
            "Target_Role": f"{gender_role} {' '.join(filter_roles)}",
            "Posted_Time": current_time,
            "Anonymity": anonymity,
            "Allowed_Users": filtered_users
        }

        if anonymity == "Signed":
            data.update({
                "Owner_Info": extracted_data["owner_info"],
                "Profile_url": extracted_data["profile_url"],
            })
        else:
            data.update({
                "Hint": extracted_data["hint"],
            })

        result = await self.fs_recruitments.add_recruit_data(owner_id=owner_id, data=data)

        if result == "ERROR":
            await interaction.edit_original_response(content=None, embed=System_Error_Embed())
        else:
            await interaction.edit_original_response(content="裏募集を編集しました。")

    async def blacklist_get(self, owner_id):
        blacklist = await self.fs_blacklist.get_list(owner_id=owner_id)
        blacklist_from = await self.fs_blacklist_from.get_list(owner_id=owner_id)
        return blacklist, blacklist_from
    
class Delete_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_recruitments = FS_Recruitments()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("裏募集を削除します。", ephemeral=True)

        result = await self.fs_recruitments.delete_data(owner_id=interaction.user.id)

        if result == "DELETE":
            await interaction.edit_original_response(content="裏募集を削除しました。")
            await interaction.channel.delete()
        else:
            await interaction.edit_original_response(content=None, embed=System_Error_Embed())

class Recruit_Check_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Recruit_Check_Button(label="記名募集確認", emoji=None, style=discord.ButtonStyle.gray, row=0, btn_type="Signed"))
        self.add_item(Recruit_Check_Button(label="匿名募集確認", emoji=None, style=discord.ButtonStyle.gray, row=0, btn_type="Anonymous"))

class Recruit_Check_Button(Button):
    def __init__(self, label, emoji, style, row, btn_type):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{btn_type}_{self.__class__.__name__}")
        self.btn_type = btn_type
        self.fs_recruitments = FS_Recruitments()

    async def callback(self, interaction: discord.Interaction):
        ok, remaining = check_button_cooldown(
            user_id=interaction.user.id,
            key=self.custom_id,      # or FILENAME, or f"{FILENAME}:{self.btn_type}"
            cooldown_seconds=10,     # ここを 60 にすれば「1分に1回」になる
        )

        if not ok:
            # まだ押せないので即レスして終了
            # 端数は丸めても良いし、そのままでもOK
            sec = int(remaining) + 1
            await interaction.response.send_message(
                content=f"このボタンはクールダウン中です。\nあと **{sec}秒** 後に再度お試しください。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        recruit_list = await self.fs_recruitments.get_recruit_data(interaction.user.id, self.btn_type)

        logger.debug(f"recruit_list: {recruit_list}")

        if not recruit_list:
            try:
                await interaction.followup.send(embed=Recruit_Result_None_Embed(), ephemeral=True)
            except HTTPException as e:
                if e.status == 429:  # レートリミット発生時
                    retry_after = int(e.response.headers.get("Retry-After", 5))  # デフォルト5秒待機
                    logger.warning(f"Rate limited. Retrying after {retry_after} seconds.")
                    await asyncio.sleep(retry_after)
                    await interaction.followup.send(embed=Recruit_Result_None_Embed(), ephemeral=True)
            return
        
        embed = Recruit_Check_Result_Embed(number=len(recruit_list))
        view = Recruit_Check_Result_View(recruit_list)

        try:
            await interaction.followup.send(content=f"ページ {view.page + 1}/{view.max_page + 1}", embed=embed, view=view, ephemeral=True)
        except HTTPException as e:
            if e.status == 429:  # レートリミット発生時
                retry_after = int(e.response.headers.get("Retry-After", 5))  # デフォルト5秒待機
                logger.warning(f"Rate limited. Retrying after {retry_after} seconds.")
                await asyncio.sleep(retry_after)
                await interaction.followup.send(content=f"ページ {view.page + 1}/{view.max_page + 1}", embed=embed, view=view, ephemeral=True)

class Recruit_Check_Result_View(View):
    def __init__(self, recruit_list):
        super().__init__(timeout=None)
        self.recruit_list = recruit_list
        self.page = 0
        self.max_page = (len(recruit_list) - 1) // 25
        self.update_menu()

        if self.max_page > 0:
            self.add_item(PrevPageButton(self))
            self.add_item(NextPageButton(self))
    
    def update_menu(self):
        start = self.page * 25
        end = start + 25
        options = [discord.SelectOption(label=f'{data["MessageID"]}.{data["Content"]}', description=data["DesireTime"], value=data["owner_id"]) for data in self.recruit_list[start:end]]
        
        if hasattr(self, "menu"):
            self.remove_item(self.menu)
        self.menu = Recruit_Check_Result_Menu(options)
        self.add_item(self.menu)

class Recruit_Check_Result_Menu(Select):
    def __init__(self, options):
        super().__init__(placeholder="確認したい募集を選択してください。", options=options, min_values=1, max_values=1)
        self.fs_recruitments = FS_Recruitments()

    async def callback(self, interaction: discord.Interaction):
        # --- (1) 最初のデフェールにもレートリミット対策を入れる ---
        try:
            await interaction.response.defer(ephemeral=True)
        except HTTPException as e:
            if e.status == 429:  # レートリミット発生時
                retry_after = int(e.response.headers.get("Retry-After", 5))  # デフォルト5秒
                logger.warning(f"初回のdeferでレートリミットに達しました。{retry_after}秒後に再試行します。")
                await asyncio.sleep(retry_after)
                # 再試行
                await interaction.response.defer(ephemeral=True)
            else:
                # その他のHTTPExceptionならそのままエラーを投げる
                raise

        # --- (2) ここから先は既存の流れと同じ ---
        owner = interaction.guild.get_member(int(self.values[0]))

        if MAIN_ROLES.MALE in [role.id for role in owner.roles]:
            color = SERVER_COLORS.MALE
        else:
            color = SERVER_COLORS.FEMALE

        data = await self.fs_recruitments.get_content_data(user_id=owner.id)
        if data is None:
            embed = Recruit_NotFound_Data_Embed()
            view = None
        elif data == "ERROR":
            embed = System_Error_Embed()
            view = None
        else:
            if data["Anonymity"] == "Signed":
                embed = Recruit_Signed_Setting_Embed(
                    user_name=owner.display_name,
                    user_id=owner.id,
                    user_avatar_url=owner.display_avatar.url,
                    profile_url=data["Profile_url"],
                    color=color,
                    number=data["Message_ID"],
                    content=data["Content"],
                    desire_time=data["Desire_Time"],
                    desire_you=data["Desire_You"],
                    message=data["Message"],
                    thread_id=data["Thread_ID"],
                    posted_time=data["Posted_Time"]
                )
            else:
                embed = Recruit_Anonymous_Setting_Embed(
                    color=color,
                    number=data["Message_ID"],
                    hint=data["Hint"],
                    content=data["Content"],
                    desire_time=data["Desire_Time"],
                    desire_you=data["Desire_You"],
                    message=data["Message"],
                    thread_id=data["Thread_ID"],
                    posted_time=data["Posted_Time"]
                )
            view = Recruit_User_View()

        # --- (3) 既存のfollowup.send(...) によるレートリミット対策はそのまま ---
        try:
            if view is not None:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except HTTPException as e:
            if e.status == 429:  # レートリミット発生時
                retry_after = int(e.response.headers.get("Retry-After", 5))  # デフォルト5秒待機
                logger.warning(f"レートリミットに達しました。{retry_after}秒後に再試行します。")
                await asyncio.sleep(retry_after)
                if view is not None:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                else:
                    await interaction.followup.send(embed=embed, ephemeral=True)

class PrevPageButton(Button):
    def __init__(self, view):
        super().__init__(label="前へ", style=discord.ButtonStyle.primary)
        self.view = view

    async def callback(self, interaction: discord.Interaction):
        if self.view.page > 0:
            self.view.page -= 1
            self.view.update_menu()
            await interaction.response.edit_message(
                content=f"ページ {self.view.page + 1}/{self.view.max_page + 1}",
                view=self.view
            )

class NextPageButton(Button):
    def __init__(self, view):
        super().__init__(label="次へ", style=discord.ButtonStyle.primary)
        self.view = view

    async def callback(self, interaction: discord.Interaction):
        if self.view.page < self.view.max_page:
            self.view.page += 1
            self.view.update_menu()
            await interaction.response.edit_message(
                content=f"ページ {self.view.page + 1}/{self.view.max_page + 1}",
                view=self.view
            )

class Recruit_User_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Stand_Button(label="立候補", emoji=DEFAULT.MALE_HEART, style=discord.ButtonStyle.gray, row=0))

class Stand_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_rec_message = FS_Rec_Message()
        self.fs_profile = FS_Profile()
        self.fs_recruitments = FS_Recruitments()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel_embed = interaction.message.embeds[0]
        panel_dict = panel_embed.to_dict()
        number = panel_dict["footer"]["text"]

        mes_data = await self.fs_rec_message.get_data(number=number, user_id=interaction.user.id)

        if mes_data:
            await interaction.followup.send(content="すでに立候補しています。", ephemeral=True)
            return

        thread_id = int(panel_embed.author.name)

        owner_id = await self.fs_recruitments.get_number_to_id(number)

        thread = interaction.guild.get_channel(thread_id) or await interaction.guild.fetch_channel(thread_id)

        profile_data = await self.fs_profile.get_profile_data(interaction.user.id)

        if profile_data is None or profile_data == "NOT_FOUND":
            await interaction.followup.send(embed=System_Profile_NotFoud_Embed(), ephemeral=True)
            return
        
        profile_id = profile_data["MESSAGE_ID"]

        if MAIN_ROLES.MALE in [role.id for role in interaction.user.roles]:
            channel_id = MAIN_CHANNELS.PROFILE_MALE
        else:
            channel_id = MAIN_CHANNELS.PROFILE_FEMALE

        profile_url = f"https://discord.com/channels/{MAIN_SERVER_ID}/{channel_id}/{profile_id}"

        embed = Receive_Embed(
            user_name = interaction.user.display_name,
            user_id = interaction.user.id,
            user_avatar_url = interaction.user.display_avatar.url,
            profile_url=profile_url,
            number=str(panel_dict["footer"]["text"])
        )

        message = await thread.send(content=f"<@{owner_id}>", embed=embed, view=Receive_View())

        result = await self.fs_rec_message.add_data(
            number = number,
            user_id = interaction.user.id,
            thread_id = thread.id,
            message_id = message.id
        )

        if result == "ERROR":
            logger.error(f"立候補データの保存に失敗しました。")

        panel_dict["title"] == "立候補しました。"
        new_panel_embed = discord.Embed.from_dict(panel_dict)

        await interaction.user.send(embed=new_panel_embed, view=Stand_View())

class Receive_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Allow_Button(label="おっけー", emoji=DEFAULT.CHECK, style=discord.ButtonStyle.gray, row=0))

class Allow_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_recruitments = FS_Recruitments()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        panel_embed = interaction.message.embeds[0]

        owner_id = interaction.user.id
        target_id = int(panel_embed.author.name)

        channel = interaction.guild.get_channel(MAIN_CHANNELS.S_RECRUIT_CREATE) or await interaction.guild.fetch_channel(MAIN_CHANNELS.S_RECRUIT_CREATE)

        new_thread = await channel.create_thread(
            name=f"✋️立候補",
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=1440
        )

        allow_embed = Allow_Embed(
            number = panel_embed.footer.text
        )

        await new_thread.send(
            content=f"<@{owner_id}> <@{target_id}>",
            embed=allow_embed
            )
        
        await interaction.edit_original_response(view=None)

class Stand_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Cancel_Button(label="取消", emoji=DEFAULT.TRASH, style=discord.ButtonStyle.gray, row=0))

class Cancel_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_rec_message = FS_Rec_Message()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        panel_embed = interaction.message.embeds[0]
        number = panel_embed.footer.text
        guild = interaction.client.get_guild(MAIN_SERVER_ID)

        data = await self.fs_rec_message.get_data(number=number, user_id=interaction.user.id)

        if data is None:
            await interaction.followup.send("該当する立候補データが見つかりませんでした。既に削除された可能性があります。", ephemeral=True)
            return
        else:
            thread_id = int(data["Thread_ID"])
            message_id = int(data["Message_ID"])

            try:
                thread = guild.get_channel(thread_id) or await guild.fetch_channel(thread_id)
                message = await thread.fetch_message(message_id)

                receive_embed = message.embeds[0]
                receive_dict = receive_embed.to_dict()

                receive_dict["title"] = "立候補が取り消されました。"
                receive_dict["description"] = ""

                receive_embed = discord.Embed.from_dict(receive_dict)

                await message.edit(embed=receive_embed, view=None)

                panel_dict = panel_embed.to_dict()
                panel_dict["title"] = "立候補を取り消しました。"

                panel_embed = discord.Embed.from_dict(panel_dict)

                await self.fs_rec_message.delete_data(number=number, user_id=interaction.user.id)
                await interaction.edit_original_response(embed=panel_embed, view=None)
            except discord.NotFound as e:
                logger.info("スレッドまたはメッセージが見つかりませんでした。", exc_info=True)
                panel_dict = panel_embed.to_dict()
                panel_dict["title"] = "裏募集がすでに削除されています。"

                panel_embed = discord.Embed.from_dict(panel_dict)
                await self.fs_rec_message.delete_data(number=number, user_id=interaction.user.id)
                await interaction.edit_original_response(embed=panel_embed, view=None)
            except Exception as e:
                logger.error("システムエラーが発生しました。", exc_info=True)
                await interaction.followup.send(embed=System_Error_Embed())