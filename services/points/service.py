# services/points/service.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, PermissionOverwrite, SelectOption

from firestores.fs_points import FS_Points

from services.points.constants import (
    EXCHANGE_EVENT_TYPE_MAP,
    EXCHANGE_THREAD_NAME_MAP,
    REQUEST_CODE_PUBLIC,
    REQUEST_NOTE_PUBLIC,
    REQUEST_POINT_PUBLIC,
    get_exchange_option,
)
from services.points.enums import Genre_Type, Points_Type
from services.points.helpers.formats import format_genre_totals
from services.points.helpers.meta import build_points_meta, send_ephemeral_error
from services.points.ui.embeds import (
    Point_Channel_Create_Embed,
    Point_Channel_Info_Embed,
    Point_Check_Result_Embed,
    Point_Exchange_Thread_Embed,
    Point_Request_Public_Embed,
    Point_Shortage_Embed,
)
from utils.discord.helpers.resolve import resolve_role, resolve_category_channel
from utils.discord.safe_calls.channel_message import safe_channel_send
from utils.discord.safe_calls.channels import safe_create_text_channel
from utils.discord.safe_calls.interaction import safe_followup_send, safe_edit_original_response
from utils.discord.safe_calls.threads import safe_create_tc_thread
from utils.emojis import DEFAULT
from utils.ids import MAIN_CATEGORIES, MAIN_ROLES

logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Asia/Tokyo")


# =========================================================
# request
# =========================================================

@dataclass
class GrantResult:
    ok: list[int]
    ng: list[int]


async def record_public_play_points(
    *,
    interaction: Interaction,
    user_ids: Sequence[int],
    fs_points: FS_Points,
) -> GrantResult:
    if not user_ids:
        await send_ephemeral_error(interaction, "対象ユーザーが見つかりませんでした。")
        return GrantResult(ok=[], ng=[])

    thread_id = interaction.channel.id if interaction.channel else None
    now = datetime.now(TIMEZONE)

    ok: list[int] = []
    ng: list[int] = []

    for uid in user_ids:
        event_id = await fs_points.record_event(
            user_id=uid,
            event_type=Points_Type.PUBLIC_PLAY,
            genre=Genre_Type.PLAY,
            delta=REQUEST_POINT_PUBLIC,
            note=REQUEST_NOTE_PUBLIC,
            ts=now,
            meta=build_points_meta(
                interaction=interaction,
                code=REQUEST_CODE_PUBLIC,
                price=REQUEST_POINT_PUBLIC,
                target_user_ids=user_ids,
                thread_id=thread_id,
            ),
        )
        if event_id:
            ok.append(uid)
        else:
            ng.append(uid)

    return GrantResult(ok=ok, ng=ng)


async def create_public_request_thread(
    *,
    interaction: Interaction,
    selected_users: list[discord.abc.User],
    thread_view: discord.ui.View | None = None,
) -> str:
    member = interaction.user

    thread = await safe_create_tc_thread(
        channel=interaction.channel,
        name=f"{DEFAULT.RATED}PP-{member.display_name}",
        private=True,
        use_queue=True,
    )

    user_mentions = " ".join(u.mention for u in selected_users)
    role_mentions = f"<@&{MAIN_ROLES.ADMINISTRATOR_ONE}>"
    mentions = f"{user_mentions} {role_mentions}"

    await safe_channel_send(
        channel=thread,
        content=mentions,
        embed=Point_Request_Public_Embed(),
        view=thread_view,
    )

    return thread.jump_url


# =========================================================
# check
# =========================================================

async def check_points_summary(
    *,
    interaction: Interaction,
    period: str,
    fs_points: FS_Points,
) -> None:
    res = await fs_points.check_totals_by_period(interaction.user.id, period=period)
    if not res or not res.get("ok"):
        err = (res or {}).get("error") or "unknown error"
        embed = Embed(title="__ポイント確認 - エラー__", description=f"```\n{err}\n```")
        await safe_followup_send(interaction=interaction, embed=embed, ephemeral=True)
        return

    label = str(res.get("label") or period)
    calc = res.get("calc") or {}

    total = int(calc.get("total_points", 0) or 0)
    totals_by_genre = dict(calc.get("totals_by_genre") or {})
    genres = format_genre_totals(
        totals_by_genre,
        drop_zero=True,
        sort_desc=True,
        max_items=25,
    )

    embed = Point_Check_Result_Embed(
        total=total,
        genres=genres,
        period_label=label,
    )

    await safe_edit_original_response(
        interaction=interaction,
        embed=embed,
        view=None,
    )


# =========================================================
# exchange
# =========================================================

async def execute_exchange(
    *,
    interaction: Interaction,
    op: SelectOption,
    fs_points: FS_Points,
    thread_view: discord.ui.View | None = None,
) -> Embed:
    user = interaction.user
    guild = interaction.guild

    summary = await fs_points.get_summary(user_id=user.id)
    total_point = int(summary["total_points"])
    use_point = int(op.description.replace(",", ""))

    if total_point < use_point:
        return Point_Shortage_Embed(user=user, total=total_point, use_points=use_point)

    prefix = op.value[:2]
    thread_name, title = EXCHANGE_THREAD_NAME_MAP.get(prefix, ("📌EXC", "交換"))

    if not op.value.startswith("02"):
        thread = await safe_create_tc_thread(
            channel=interaction.channel,
            name=f"{thread_name}-{user.display_name}",
            private=True,
            invitable=False,
            use_queue=True,
        )

        await safe_channel_send(
            channel=thread,
            content=f"{user.mention} <@&{MAIN_ROLES.ADMINISTRATOR_ONE}>",
            embed=Point_Exchange_Thread_Embed(
                user=user,
                title=title,
                selected=op.label,
                use_points=use_point,
                op_value=op.value,
            ),
            view=thread_view,
        )

        return Point_Channel_Create_Embed(jump_url=thread.jump_url)

    overwrites: dict = {}
    everyone = guild.default_role
    admin_role = await resolve_role(guild=guild, role_id=MAIN_ROLES.ADMINISTRATOR_TWO)
    member_role = await resolve_role(guild=guild, role_id=MAIN_ROLES.MEMBER)
    p_member_role = await resolve_role(guild=guild, role_id=MAIN_ROLES.P_MEMBER)
    if admin_role:
        overwrites[admin_role] = PermissionOverwrite(view_channel=True)
    overwrites[everyone] = PermissionOverwrite(view_channel=False, connect=False)
    overwrites[user] = PermissionOverwrite(view_channel=True, manage_channels=True, manage_messages=True, manage_roles=True)
    if member_role:
        overwrites[member_role] = PermissionOverwrite(view_channel=False, send_messages=False)
    if p_member_role:
        overwrites[p_member_role] = PermissionOverwrite(view_channel=False, send_messages=False)

    category = await resolve_category_channel(guild=guild, channel_id=MAIN_CATEGORIES.PRIVATE_TC)

    new_tc = await safe_create_text_channel(
        guild=guild,
        name=f"{user.display_name}の部屋",
        category=category,
        overwrites=overwrites,
        use_queue=True,
    )

    await safe_channel_send(
        channel=new_tc,
        content=f"{user.mention}",
        embed=Point_Channel_Info_Embed(),
    )

    now = datetime.now(TIMEZONE)
    await fs_points.record_event(
        user_id=user.id,
        event_type=Points_Type.USE_PRIVATE_TC,
        genre=Genre_Type.USE,
        delta=-use_point,
        note=op.label,
        ts=now,
        meta={
            "code": op.value,
            "price": op.description,
            "executor_id": f"{user.id}",
            "channel_id": f"{new_tc.id}",
        },
    )

    return Point_Channel_Create_Embed(jump_url=new_tc.jump_url)


async def confirm_exchange_grant(
    *,
    user: discord.Member,
    value: str,
    fs_points: FS_Points,
) -> tuple[SelectOption, int]:
    op = get_exchange_option(value)
    event_type = EXCHANGE_EVENT_TYPE_MAP.get(op.value)
    now = datetime.now(TIMEZONE)

    await fs_points.record_event(
        user_id=user.id,
        event_type=event_type,
        genre=Genre_Type.USE,
        delta=-int(op.description.replace(",", "")),
        ts=now,
        meta={
            "code": op.value,
            "price": op.description,
            "executor_id": f"{user.id}",
        },
    )

    summary = await fs_points.get_summary(user_id=user.id)
    total_point = int(summary["total_points"])

    return op, total_point
