# services/points/ui/views.py

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

import discord
from discord import ButtonStyle, Embed, Interaction
from discord.ui import Button, Select, UserSelect, View

from firestores.fs_points import FS_Points

from services.points.constants import CHECK_OP, REQUEST_OP, USE_OP, get_use_option
from services.points.service import (
    check_points_summary,
    close_current_thread,
    confirm_thread_point_use,
    consume_points_and_open_destination,
    create_public_request_thread,
    open_public_request_review,
    record_public_play_points,
)
from services.points.ui.embeds import (
    Point_Check_Embed,
    Point_Request_Embed,
    Point_Request_Public_UserSelect_Embed,
    Point_Use_Embed,
    Thread_Close_Embed,
)
from utils.discord_helpers.user_ids import coerce_user_ids
from utils.discord_tasks.channel_message import safe_message_delete
from utils.discord_tasks.interaction import (
    safe_defer,
    safe_response_edit,
    safe_response_send,
)
from utils.emojis import DEFAULT

FILENAME = "Points_Views"


# =========================================================
# base
# =========================================================

def make_custom_id(name: str) -> str:
    return f"{FILENAME}_{name}"


class BaseButton(Button):
    def __init__(
        self,
        *,
        label: str,
        emoji: Any,
        style: ButtonStyle,
        row: Optional[int] = None,
        disabled: bool = False,
        custom_id_suffix: Optional[str] = None,
    ):
        custom_id_name = self.__class__.__name__
        if custom_id_suffix:
            custom_id_name = f"{custom_id_name}_{custom_id_suffix}"

        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            disabled=disabled,
            custom_id=make_custom_id(custom_id_name),
        )


class BaseSelect(Select):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("custom_id", make_custom_id(self.__class__.__name__))
        super().__init__(**kwargs)


class SingleItemView(View):
    def __init__(self, item: discord.ui.Item[Any], *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.add_item(item)


class OpenViewButton(BaseButton):
    def __init__(
        self,
        *,
        label: str,
        emoji: Any,
        style: ButtonStyle,
        row: int,
        embed_factory: Callable[[], Embed],
        view_factory: Callable[[], View],
        custom_id_suffix: str,
    ):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            row=row,
            custom_id_suffix=custom_id_suffix,
        )
        self.embed_factory = embed_factory
        self.view_factory = view_factory

    async def callback(self, interaction: Interaction):
        await safe_response_send(
            interaction=interaction,
            embed=self.embed_factory(),
            view=self.view_factory(),
            ephemeral=True,
        )


# =========================================================
# common
# =========================================================

class CancelEditButton(BaseButton):
    def __init__(self):
        super().__init__(
            label="キャンセル",
            emoji=DEFAULT.CROSS,
            style=ButtonStyle.gray,
            row=1,
        )

    async def callback(self, interaction: Interaction):
        await safe_response_edit(
            interaction=interaction,
            content="🗑️キャンセルしました。",
            view=None,
        )


class ThreadCloseAskButton(BaseButton):
    def __init__(self):
        super().__init__(
            label="スレッドを閉じる",
            emoji=DEFAULT.TRASH,
            style=ButtonStyle.gray,
            row=0,
        )

    async def callback(self, interaction: Interaction):
        await safe_response_send(
            interaction=interaction,
            embed=Thread_Close_Embed(),
            view=ThreadCloseConfirmView(),
            ephemeral=True,
        )


class ThreadCloseConfirmButton(BaseButton):
    def __init__(self):
        super().__init__(
            label="おっけー",
            emoji=DEFAULT.CIRCLE,
            style=ButtonStyle.gray,
            row=0,
        )

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)
        await close_current_thread(interaction=interaction)


class ThreadCloseCancelButton(BaseButton):
    def __init__(self):
        super().__init__(
            label="やめとく",
            emoji=DEFAULT.CROSS,
            style=ButtonStyle.gray,
            row=0,
        )

    async def callback(self, interaction: Interaction):
        await safe_response_send(
            interaction=interaction,
            content="キャンセルしました。",
            ephemeral=True,
        )
        if interaction.message is not None:
            await safe_message_delete(message=interaction.message)


class ThreadCloseConfirmView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ThreadCloseConfirmButton())
        self.add_item(ThreadCloseCancelButton())


# =========================================================
# request
# =========================================================

class RequestSelect(BaseSelect):
    def __init__(self):
        super().__init__(
            placeholder="コンテンツを選択してください。",
            min_values=1,
            max_values=1,
            options=REQUEST_OP,
            row=1,
        )

    async def callback(self, interaction: Interaction):
        selected_value = self.values[0]

        if selected_value == "01":
            view = PublicRequestUserSelectView(selected_value=selected_value)

            await safe_response_send(
                interaction=interaction,
                embed=Point_Request_Public_UserSelect_Embed(),
                view=view,
                ephemeral=True,
            )
            return

        await safe_response_send(
            interaction=interaction,
            content="対象項目の読み込みに失敗しました。",
            ephemeral=True,
        )


class PublicRequestUserSelect(UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="ユーザーを選択してください。",
            min_values=1,
            max_values=25,
            custom_id=make_custom_id(self.__class__.__name__),
        )

    async def callback(self, interaction: Interaction):
        view = self.view
        if not isinstance(view, PublicRequestUserSelectView):
            await safe_response_send(
                interaction=interaction,
                content="Viewの取得に失敗しました。",
                ephemeral=True,
            )
            return

        view.selected_users = list(self.values)
        view.confirm_button.disabled = False
        await interaction.response.edit_message(view=view)


class PublicRequestCreateThreadButton(BaseButton):
    def __init__(self, *, disabled: bool = True):
        super().__init__(
            label="おっけー",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.blurple,
            row=1,
            disabled=disabled,
        )

    async def callback(self, interaction: Interaction):
        view = self.view
        if not isinstance(view, PublicRequestUserSelectView):
            await safe_response_send(
                interaction=interaction,
                content="Viewの取得に失敗しました。",
                ephemeral=True,
            )
            return

        if not view.selected_value:
            await safe_response_send(
                interaction=interaction,
                content="申請項目の取得に失敗しました。もう一度最初から選択してください。",
                ephemeral=True,
            )
            return

        await safe_defer(interaction=interaction, ephemeral=True)
        await create_public_request_thread(
            interaction=interaction,
            selected_users=view.selected_users,
            selected_value=view.selected_value,
            thread_view=PublicRequestThreadView(),
        )


class PublicRequestUserSelectView(View):
    def __init__(self, *, selected_value: str | None = None):
        super().__init__(timeout=None)
        self.selected_value = selected_value
        self.selected_users: list[discord.abc.User] = []
        self.confirm_button = PublicRequestCreateThreadButton(disabled=True)

        self.add_item(PublicRequestUserSelect())
        self.add_item(self.confirm_button)
        self.add_item(CancelEditButton())

class PublicRequestReviewButton(BaseButton):
    def __init__(self):
        super().__init__(
            label="確定",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.blurple,
            row=0,
        )

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)

        msg = interaction.message
        message_content = msg.content if msg else ""
        user_ids = sorted(coerce_user_ids(message_content))

        await open_public_request_review(
            interaction=interaction,
            message_content=message_content,
            confirm_view=PublicRequestConfirmView(user_ids=user_ids),
        )


class PublicRequestConfirmButton(BaseButton):
    def __init__(self, *, user_ids: Sequence[int], fs_points: Optional[FS_Points] = None):
        super().__init__(
            label="おっけー",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
        )
        self.user_ids = list(user_ids)
        self.fs_points = fs_points or FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)
        await record_public_play_points(
            interaction=interaction,
            user_ids=self.user_ids,
            fs_points=self.fs_points,
        )


class PublicRequestConfirmView(View):
    def __init__(self, *, user_ids: Sequence[int]):
        super().__init__(timeout=None)
        self.add_item(PublicRequestConfirmButton(user_ids=user_ids))


class PublicRequestThreadView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ThreadCloseAskButton())
        self.add_item(PublicRequestReviewButton())


# =========================================================
# check
# =========================================================

class CheckSelect(BaseSelect):
    def __init__(self, *, fs_points: Optional[FS_Points] = None):
        super().__init__(
            placeholder="期間を選択してください。",
            min_values=1,
            max_values=1,
            options=CHECK_OP,
            row=1,
        )
        self.fs_points = fs_points or FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)
        await check_points_summary(
            interaction=interaction,
            period=self.values[0],
            fs_points=self.fs_points,
        )


# =========================================================
# use
# =========================================================

class UseSelect(BaseSelect):
    def __init__(self, *, fs_points: Optional[FS_Points] = None):
        super().__init__(
            placeholder="コンテンツを選択してください。",
            min_values=1,
            max_values=1,
            options=USE_OP,
        )
        self.fs_points = fs_points or FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)

        selected_option = get_use_option(self.values[0])
        if selected_option is None:
            await safe_response_send(
                interaction=interaction,
                content="利用項目の取得に失敗しました。",
                ephemeral=True,
            )
            return

        await consume_points_and_open_destination(
            interaction=interaction,
            selected_option=selected_option,
            fs_points=self.fs_points,
            thread_view=PointsThreadView(),
        )


class PointsThreadConfirmButton(BaseButton):
    def __init__(self, *, fs_points: Optional[FS_Points] = None):
        super().__init__(
            label="確定",
            emoji=DEFAULT.CHECK,
            style=ButtonStyle.gray,
            row=0,
        )
        self.fs_points = fs_points or FS_Points()

    async def callback(self, interaction: Interaction):
        await safe_defer(interaction=interaction, ephemeral=True)
        await confirm_thread_point_use(
            interaction=interaction,
            fs_points=self.fs_points,
        )


class PointsThreadView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ThreadCloseAskButton())
        self.add_item(PointsThreadConfirmButton())


# =========================================================
# panel
# =========================================================

class Point_Panel_View(View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(
            OpenViewButton(
                label="申請",
                emoji=DEFAULT.MEMO,
                style=ButtonStyle.gray,
                row=0,
                embed_factory=Point_Request_Embed,
                view_factory=lambda: SingleItemView(RequestSelect(), timeout=None),
                custom_id_suffix="request",
            )
        )

        self.add_item(
            OpenViewButton(
                label="確認",
                emoji=DEFAULT.GRAPH,
                style=ButtonStyle.gray,
                row=0,
                embed_factory=Point_Check_Embed,
                view_factory=lambda: SingleItemView(CheckSelect(), timeout=None),
                custom_id_suffix="check",
            )
        )

        self.add_item(
            OpenViewButton(
                label="利用",
                emoji=DEFAULT.CHECK,
                style=ButtonStyle.gray,
                row=0,
                embed_factory=Point_Use_Embed,
                view_factory=lambda: SingleItemView(UseSelect(), timeout=None),
                custom_id_suffix="use",
            )
        )