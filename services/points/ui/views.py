# services/points/ui/views.py

from __future__ import annotations

from typing import Optional

from discord import ButtonStyle, Interaction, Member, SelectOption
from discord.ui import Button, Select, UserSelect, View, LayoutView, TextDisplay, Section

from firestores.fs_points import FS_Points

from services.points.constants import CHECK_OP, EXCHANGE_OP, get_exchange_option
from services.points.service import (
    check_points_summary,
    confirm_exchange_grant,
    create_public_request_thread,
    execute_exchange,
    record_public_play_points,
)
from services.points.ui.embeds import (
    Point_Check_Embed,
    Point_Request_Public_Select_Embed,
    Point_Request_Confirm_Check_Embed,
    Point_Request_Confirm_Result_Embed,
    Point_Exchange_Embed,
    Point_Exchange_Review_Embed,
    Point_Exchange_Thread_Review_Embed,
    Point_Exchange_Thread_Result_Embed,
    Point_Thread_Close_Embed,
    Point_Channel_Create_Embed,
)
from services.system.embeds import No_Permission_Embed

from utils.discord.helpers.user_ids import coerce_user_ids
from utils.discord.helpers.resolve import resolve_member
from utils.discord.helpers.check import has_any_role
from utils.discord.safe_calls.interaction import (
    safe_defer,
    safe_response_edit,
    safe_response_send,
    safe_followup_send,
    safe_delete_original_response,
    safe_edit_original_response,
)
from utils.discord.safe_calls.threads import safe_delete_tc_thread
from utils.discord.helpers.components import Menu_Container
from utils.emojis import DEFAULT, CUSTOM
from utils.ids import MAIN_ROLES


FILENAME = "Points_Views"


class Point_Check_Button(Button):
    def __init__(self):
        super().__init__(label="確認", emoji=DEFAULT.EYES, style=ButtonStyle.gray, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        embed = Point_Check_Embed()
        view = Point_Check_View()
        await safe_response_send(
            interaction=interaction,
            embed=embed,
            view=view,
            ephemeral=True
            )

class Point_Check_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Check_Select())

class Point_Check_Select(Select):
    def __init__(self, *, fs_points: Optional[FS_Points] = None):
        super().__init__(
            placeholder="期間を選択してください。",
            min_values=1,
            max_values=1,
            options=CHECK_OP,
            row=0,
        )
        self.fs_points = fs_points or FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)
        await check_points_summary(
            interaction=interaction,
            period=self.values[0],
            fs_points=self.fs_points,
        )

class Point_Request_Public_Button(Button):
    def __init__(self):
        super().__init__(label="申請", emoji=DEFAULT.RATED, style=ButtonStyle.gray, custom_id=f"{FILENAME}_{self.__class__.__name__}")

    async def callback(self, interaction: Interaction):
        embed = Point_Request_Public_Select_Embed()
        view = Point_Request_Public_View()

        await safe_response_send(
            interaction=interaction,
            embed=embed,
            view=view,
            ephemeral=True
        )

class Point_Request_Public_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Request_Public_UserSelect())
        self.add_item(Point_Request_Public_Confirm_Button())

class Point_Request_Public_UserSelect(UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="公開した相手を選択",
            min_values=1,
            max_values=25,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction)

        self.view.selected_users = self.values

        for item in self.view.children:
            if isinstance(item, Point_Request_Public_Confirm_Button):
                item.disabled = False
                break

        await safe_edit_original_response(interaction=interaction, view=self.view)

class Point_Request_Public_Confirm_Button(Button):
    def __init__(self):
        super().__init__(
            label="おっけー",
            style=ButtonStyle.green,
            disabled=True,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction)

        selected_users = getattr(self.view, "selected_users", [])

        jump_url = await create_public_request_thread(
            interaction=interaction,
            selected_users=selected_users,
            thread_view=Point_Request_Public_Thread_View(),
        )

        await safe_edit_original_response(
            interaction=interaction,
            embed=Point_Channel_Create_Embed(jump_url),
            view=None
        )
        
class Point_Request_Public_Thread_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Thread_Close_Button())
        self.add_item(Point_Request_Public_Grant_Button())

class Point_Thread_Close_Button(Button):
    def __init__(self):
        super().__init__(
            label="スレッドを閉じる",
            emoji=DEFAULT.TRASH,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
            )
    
    async def callback(self, interaction: Interaction):
        embed = Point_Thread_Close_Embed()
        view = Point_Thread_Close_View()
        await safe_response_send(
            interaction=interaction,
            embed=embed,
            view=view
        )

class Point_Thread_Close_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Thread_Close_Confirm_Button())
        self.add_item(Point_Thread_Close_Cancel_Button())

class Point_Thread_Close_Confirm_Button(Button):
    def __init__(self):
        super().__init__(
            label="おっけー",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await safe_response_send(
            interaction=interaction,
            content="スレッドを削除します。"
        )

        await safe_delete_tc_thread(
            thread = interaction.channel,
            reason = "スレッド削除コマンド",
            use_queue=True
        )

class Point_Thread_Close_Cancel_Button(Button):
    def __init__(self):
        super().__init__(
            label="キャンセル",
            emoji=DEFAULT.CROSS,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await safe_delete_original_response(interaction=interaction)

class Point_Request_Public_Grant_Button(Button):
    def __init__(self):
        super().__init__(
            label="付与",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)

        user = interaction.user
        if not has_any_role(user, [MAIN_ROLES.ADMINISTRATOR_ONE, MAIN_ROLES.ADMINISTRATOR_TWO]):
            await safe_followup_send(
                interaction=interaction,
                embed=No_Permission_Embed(),
                ephemeral=True
            )
            return

        msg = interaction.message
        content = msg.content

        user_ids = coerce_user_ids(content)
        guild = interaction.guild

        members = []
        for user_id in user_ids:
            member = await resolve_member(guild=guild, user_id=user_id)
            if member:
                members.append(member)

        mention_list = "\n".join(
            f"{i + 1:02d}. {m.display_name} ({m.mention})"
            for i, m in enumerate(members)
        )

        embed = Point_Request_Confirm_Check_Embed(
            mention_list=mention_list
        )
        view = Point_Request_Public_Grant_View(user_ids=user_ids)

        await safe_followup_send(
            interaction=interaction,
            embed=embed,
            view=view,
            ephemeral=True
        )

class Point_Request_Public_Grant_View(View):
    def __init__(self, user_ids):
        super().__init__(timeout=None)
        self.add_item(Point_Request_Public_Grant_Confirm_Button(user_ids))

class Point_Request_Public_Grant_Confirm_Button(Button):
    def __init__(self, user_ids):
        super().__init__(
            label="おっけー",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )
        self.user_ids = user_ids
        self.fs_points = FS_Points()
    
    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)

        result = await record_public_play_points(
            interaction=interaction,
            user_ids=self.user_ids,
            fs_points=self.fs_points,
        )

        guild = interaction.guild

        async def fmt(uids: list[int]) -> str:
            lines = []
            for i, uid in enumerate(uids):
                member = await resolve_member(guild=guild, user_id=uid)
                if member:
                    lines.append(f"{i + 1:02d}. {member.display_name} ({member.mention})")
                else:
                    lines.append(f"{i + 1:02d}. <@{uid}>")
            return "\n".join(lines)

        ok_text = await fmt(result.ok)
        ng_text = await fmt(result.ng)

        await safe_followup_send(
            interaction=interaction,
            embed=Point_Request_Confirm_Result_Embed(ok_text=ok_text, ng_text=ng_text),
            ephemeral=True,
        )

class Point_Exchange_Button(Button):
    def __init__(self):
        super().__init__(
            label="交換",
            emoji=DEFAULT.RESET,
            style=ButtonStyle.gray,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        embed = Point_Exchange_Embed()
        view = Point_Exchange_View()
        await safe_response_send(
            interaction=interaction,
            embed=embed,
            view=view,
            ephemeral=True
            )
        
class Point_Exchange_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Exchange_Select())

class Point_Exchange_Select(Select):
    def __init__(self):
        super().__init__(
            placeholder="使用したいコンテンツを選択してください。",
            min_values=1,
            max_values=1,
            options=EXCHANGE_OP,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)

        op = get_exchange_option(self.values[0])

        embed = Point_Exchange_Review_Embed(op=op)
        view = Point_Exchange_Check_View(op=op)

        await safe_edit_original_response(
            interaction=interaction,
            embed=embed,
            view=view
            )
        
class Point_Exchange_Check_View(View):
    def __init__(self, op):
        super().__init__(timeout=None)
        self.add_item(Point_Exchange_Confirm_Button(op))
        self.add_item(Point_Exchange_Cancel_Button())

class Point_Exchange_Confirm_Button(Button):
    def __init__(self, op: SelectOption):
        super().__init__(
            label="おっけー",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )
        self.op = op
        self.fs_point = FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction)
        embed = await execute_exchange(
            interaction=interaction,
            op=self.op,
            fs_points=self.fs_point,
            thread_view=Point_Exchange_Thread_View(),
        )
        await safe_edit_original_response(interaction=interaction, embed=embed)

class Point_Exchange_Cancel_Button(Button):
    def __init__(self):
        super().__init__(
            label="キャンセル",
            emoji=DEFAULT.TRASH,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        await safe_response_edit(
            interaction=interaction,
            content="-# キャンセルしました。",
            view=None,
        )

class Point_Exchange_Thread_View(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Thread_Close_Button())
        self.add_item(Point_Exchange_Thread_Grant_Button())

class Point_Exchange_Thread_Grant_Button(Button):
    def __init__(self):
        super().__init__(
            label="確定",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )

    async def callback(self, interaction: Interaction):
        user = interaction.user
        if not has_any_role(user, [MAIN_ROLES.ADMINISTRATOR_ONE, MAIN_ROLES.ADMINISTRATOR_TWO]):
            await safe_response_send(
                interaction=interaction,
                embed=No_Permission_Embed(),
                ephemeral=True
            )
            return

        msg = interaction.message
        panel_embed = msg.embeds[0]
        user_id = int(panel_embed.author.name)
        guild = interaction.guild
        user = await resolve_member(guild=guild, user_id=user_id)
        value = panel_embed.footer.text
        
        embed = Point_Exchange_Thread_Review_Embed(user=user)
        view = Point_Exchange_Thread_Grant_View(user=user, value=value)

        await safe_response_send(
            interaction=interaction,
            embed=embed,
            view=view,
            ephemeral=True
        )

class Point_Exchange_Thread_Grant_View(View):
    def __init__(self, user: Member, value):
        super().__init__(timeout=None)
        self.add_item(Point_Exchange_Thread_Grant_Confirm_Button(user, value))

class Point_Exchange_Thread_Grant_Confirm_Button(Button):
    def __init__(self, user: Member, value):
        super().__init__(
            label="おっけー",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
            custom_id=f"{FILENAME}_{self.__class__.__name__}"
        )
        self.user = user
        self.value = value
        self.fs_points = FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)
        op, total_point = await confirm_exchange_grant(
            user=self.user,
            value=self.value,
            fs_points=self.fs_points,
        )
        embed = Point_Exchange_Thread_Result_Embed(option=op, total_point=total_point)
        await safe_followup_send(interaction=interaction, embed=embed)


# =========================================================
# panel
# =========================================================

class Point_Manage_Panel_Container(Menu_Container):
    def __init__(self):
        super().__init__(
            TextDisplay(f"## {CUSTOM.TOKEN}ELECTOKEN管理メニュー"),
            Section(
                TextDisplay("トークン数の確認を行います。"),
                accessory=Point_Check_Button()
            ),
            Section(
                TextDisplay("公開のトークン申請を行います。"),
                accessory=Point_Request_Public_Button()
            ),
            Section(
                TextDisplay("トークンの交換を行えます。"),
                accessory=Point_Exchange_Button()
            )
        )

class Point_Manage_Panel_View(LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Point_Manage_Panel_Container())