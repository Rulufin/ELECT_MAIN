import discord
from discord import (
    app_commands, Interaction, Embed, PermissionOverwrite,
    ButtonStyle, TextStyle,
    TextChannel, ForumChannel, Thread, SelectOption
)
from discord.ui import (
    View, Button, Modal, Select,
    TextInput
)

import textwrap
import logging
from typing import List, Dict, Any

from services.points.ui.embeds import (
    Point_Request_Embed, Point_Check_Embed, Point_Use_Embed,
    Point_Request_Public_UserSelect_Embed, Point_Request_Public_Embed,
    Points_Shortage_Embed, Points_Thread_Embed, Thread_Close_Embed,
    Create_Channel_Embed, Channel_Information_Embed,
)
from services.points.helpers.formats import format_genre_totals

from utils.emojis import DEFAULT, CUSTOM
from utils.ids import MAIN_CATEGORIES, MAIN_ROLES
from utils.enum import Points_Type, Genre_Type

from firestores.fs_points import FS_Points

from utils.discord_tasks.interaction import (
    safe_defer, 
    safe_response_send, safe_response_edit, safe_followup_send,
    safe_edit_original_response
)
from utils.discord_tasks.channel_message import (
    safe_channel_send, safe_message_edit, safe_message_delete
)
from utils.discord_tasks.channels import (
    safe_create_text_channel, safe_create_voice_channel, safe_create_forum_channel,
    safe_channel_edit, safe_channel_delete
)
from utils.discord_tasks.threads import (
    safe_create_tc_thread, safe_edit_tc_thread, safe_delete_tc_thread,
    safe_create_forum_thread, safe_edit_forum_thread, safe_delete_forum_thread
)

FILENAME = "Points_Views"

logger = logging.getLogger(__name__)

REQUEST_OP = [
    SelectOption(label="01. 公開", value="01", description="公開を行った申請はこちら")
]

CHECK_OP = [
    SelectOption(label="01. 1周間", value="Weekly", description="月～日でポイント集計"),
    SelectOption(label="02. 今月", value="Monthly", description="今月のポイント集計"),
    SelectOption(label="03. 全体", value="All", description="全体のポイント集計"),
]

USE_OP = [
    SelectOption(label="01-01. アイコンor絵文字作成", value="01-01", description="3,000"),
    SelectOption(label="02-01. 個人TC作成", value="02-01", description="1,000"),
    SelectOption(label="03-01. 専用ロール作成", value="03-01", description="1,000"),
    SelectOption(label="03-02. 専用ロールの名前を変更", value="03-02", description="1,000"),
    SelectOption(label="03-03. 専用ロールの色を変更", value="03-03", description="1,000"),
    SelectOption(label="03-04. 専用ロールのスタイル強化", value="03-04", description="1,000"),
    SelectOption(label="03-05. 専用ロールにアイコンをつける", value="03-05", description="1,000"),
    SelectOption(label="99-01. かーくんにネタを振れる", value="99-01", description="500"),
    SelectOption(label="99-02. わさびレシピをもらえる", value="99-02", description="500"),
]

USE_OP_MAP = {op.value: op for op in USE_OP}

class Point_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Request_Button(label="申請", emoji=DEFAULT.MEMO, style=ButtonStyle.gray, row=0))
        self.add_item(Point_Check_Button(label="確認", emoji=DEFAULT.GRAPH, style=ButtonStyle.gray, row=0))
        self.add_item(Point_Use_Button(label="利用", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=0))

class Point_Request_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        embed = Point_Request_Embed()
        view = Point_Request_View()
        await safe_response_send(interaction=interaction, embed=embed, view=view, ephemeral=True)

class Point_Request_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Request_Select())

class Point_Request_Select(Select):
    def __init__(self):
        super().__init__(
            placeholder="コンテンツを選択してください。",
            max_values=1,
            min_values=1,
            options=REQUEST_OP,
            row=1,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        type_map = {
            "01": ()
        }

class Point_Check_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        embed = Point_Check_Embed()
        view = Point_Check_View()
        await safe_response_send(interaction=interaction, embed=embed, view=view, ephemeral=True)

class Point_Check_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Check_Select())

class Point_Check_Select(Select):
    def __init__(self):
        super().__init__(
            placeholder="期間を選択してください。",
            max_values=1,
            min_values=1,
            options=CHECK_OP,
            row=1,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )
        self.fs_points = FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)

        period = self.values[0]  # "Weekly" / "Monthly" / "All"

        res = await self.fs_points.check_totals_by_period(interaction.user.id, period=period)
        if not res or not res.get("ok"):
            err = (res or {}).get("error") or "unknown error"
            embed = Embed(title="__ポイント確認 - エラー__", description=f"```\n{err}\n```")
            await safe_followup_send(interaction=interaction, embed=embed, ephemeral=True)
            return

        label = str(res.get("label") or period)
        calc = res.get("calc") or {}

        total = int(calc.get("total_points", 0) or 0)
        totals_by_genre = dict(calc.get("totals_by_genre") or {})

        genres = format_genre_totals(totals_by_genre, drop_zero=True, sort_desc=True, max_items=25)

        embed = Point_Result_Embed(total=total, genres=genres, period_label=label)
        await safe_followup_send(interaction=interaction, embed=embed, ephemeral=True)

class Point_Result_Embed(Embed):
    def __init__(self, *, total: int, genres: List[Dict[str, int | str]], period_label: str):
        super().__init__(
            title="__ポイント確認 - 結果__",
            description=textwrap.dedent(
                f"""
                期間：{period_label}
                """
            ).strip(),
        )

        self.add_field(name="__全体__", value=f"{int(total):,} pt", inline=False)

        if not genres:
            self.add_field(name="__内訳__", value="（該当なし）", inline=False)
            return

        # 1フィールドにまとめたいならここを join にするのもアリ
        for g in genres:
            name = str(g["name"])
            points = int(g["points"])
            self.add_field(name=f"__{name}__", value=f"{points:,} pt", inline=True)

class Point_Use_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id=f"{FILENAME}_{self.__class__.__name__}",
        )

    async def callback(self, interaction: Interaction):
        embed = Point_Use_Embed()
        view = Point_Use_View()
        await safe_response_send(interaction=interaction, embed=embed, view=view, ephemeral=True)

class Point_Use_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Use_Select())

class Point_Use_Select(Select):
    def __init__(self):
        super().__init__(
            placeholder="コンテンツを選択してください。",
            min_values=1, max_values=1, options=USE_OP,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
            )
        self.fs_points = FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction)

        user = interaction.user
        guild = interaction.guild
        selected_value = self.values[0]

        selected_option = next(
            (opt for opt in self.options if opt.value == selected_value),
            None
        )

        if selected_option is None:
            return

        use_points = int(selected_option.description)

        summary = await self.fs_points.get_summary(user_id=user.id)
        total = summary.get("total_points", 0)

        if use_points > total:
            embed = Points_Shortage_Embed(user=user, total=total, use_points=use_points)
            await safe_followup_send(interaction=interaction, embed=embed, ephemeral=True)
            return


        # =========================
        # グループ別スレ名
        # =========================
        group_code = selected_value.split("-")[0]

        THREAD_NAME_MAP = {
            "01": ("🎨EM", "アイコンor絵文字関連", Points_Type.USE_ICON_EMOJI),
            "02": ("📝MY", "個人チャンネル関連", Points_Type.USE_PRIVATE),
            "03": ("🎖️RL", "専用ロール関連", Points_Type.USE_ROLE),
            "99": ("🎲OT", "その他", Points_Type.USE_OTHER),
        }

        if group_code == "02":
            thread_base, title, pt_type = THREAD_NAME_MAP.get(group_code, ("📌PT", "その他", Points_Type.USE_OTHER))
            thread_name = f"{thread_base}-{user.display_name}"

            thread = await safe_create_tc_thread(
                channel=interaction.channel,
                name=thread_name,
                invitable=False,
                use_queue=True
            )

            create_embed = Create_Channel_Embed(jump_url=thread.jump_url)

            await safe_followup_send(interaction=interaction, embed=create_embed, ephemeral=True)

            thread_embed = Points_Thread_Embed(user=user, title=title, selected=selected_option.label, use_points=use_points, op_value=selected_value, pt_type=pt_type)
            thread_view = Points_Thread_View()

            await thread.send(embed=thread_embed, view=thread_view)

        else:
            category = guild.get_channel(MAIN_CATEGORIES.PRIVATE_TC) or await guild.fetch_channel(MAIN_CATEGORIES.PRIVATE_TC)
            admin = guild.get_role(MAIN_ROLES.ADMINISTRATOR_ONE) or await guild.fetch_role(MAIN_ROLES.ADMINISTRATOR_ONE)
            member = guild.get_role(MAIN_ROLES.MEMBER) or await guild.fetch_role(MAIN_ROLES.MEMBER)
            p_member = guild.get_role(MAIN_ROLES.P_MEMBER) or await guild.fetch_role(MAIN_ROLES.P_MEMBER)

            overwrites: dict[Any, PermissionOverwrite] = {}
            overwrites[guild.default_role] = PermissionOverwrite(view_channel=False)
            overwrites[admin] = PermissionOverwrite(view_channel=True)
            overwrites[user] = PermissionOverwrite(view_channel=True, manage_roles=True, manage_channels=True, manage_messages=True)
            overwrites[member] = PermissionOverwrite(view_channel=False)
            overwrites[p_member] = PermissionOverwrite(view_channel=False)

            tc = await safe_create_text_channel(guild=guild, category=category, name=user.display_name, overwrites=overwrites)

            await self.fs_points.record_event(
                user_id=user.id, 
                event_type=pt_type,
                genre=Genre_Type.USE,
                delta = -use_points,
                note = selected_option.label,
                meta = {
                    "code": selected_option.value,
                    "price": use_points
                    }
                )

            create_embed = Create_Channel_Embed(jump_url=tc.jump_url)

            await safe_followup_send(interaction=interaction, embed=create_embed, ephemeral=True)

            await tc.send(embed=Channel_Information_Embed())

class Points_Thread_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Close_Button(label="スレッドを閉じる", emoji=DEFAULT.TRASH, style=ButtonStyle.gray, row=0))
        self.add_item(Confirmed_Button(label="確定", emoji=DEFAULT.CHECK, style=ButtonStyle.gray, row=0))

class Close_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
    
    async def callback(self, interaction: Interaction):
        embed = Thread_Close_Embed()
        view = Points_Close_View()

        await safe_response_send(interaction=interaction, embed=embed, view=view)

class Points_Close_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Close_OK_Button(label="おっけー", emoji=DEFAULT.CIRCLE, style=ButtonStyle.gray, row=0))
        self.add_item(Cancel_Button(label="やめとく", emoji=DEFAULT.CROSS, style=ButtonStyle.gray, row=0))

class Close_OK_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction)

        thread: Thread = interaction.channel

        await thread.remove_user(interaction.user)

        await safe_edit_tc_thread(thread=thread, archived=True)

        await safe_followup_send(content="スレッドを閉じました。")

class Cancel_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        await safe_response_send(interaction=interaction, content="キャンセルしました。", ephemeral=True)

        await safe_message_delete(message=interaction.message)

class Confirmed_Button(Button):
    def __init__(self, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row, custom_id=f"{FILENAME}_{self.__class__.__name__}")
        self.fs_points = FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction)

        msg = interaction.message
        embed = msg.embeds[0]

        user_id = int(embed.author.name)
        footer_text = embed.footer.text

        footer_list = footer_text.strip(" / ").split(" / ")

        roles = [footer_list[0], footer_list[1]]
        op_value = footer_list[2]
        pt_type = footer_list[3]

        owner = interaction.user

        if not any(role.id in roles for role in owner.roles):
            await safe_followup_send(
                interaction=interaction,
                content="これは管理者専用ボタンです。",
                ephemeral=True
            )
            return

        option = USE_OP_MAP.get(op_value)

        if option:
            use_points = int(option.description.replace(",", ""))

        await self.fs_points.record_event(
            user_id=user_id, 
            event_type=pt_type,
            genre=Genre_Type.USE,
            delta = -use_points,
            note = op_value,
            meta = {
                "code": op_value,
                "price": use_points
                }
            )

