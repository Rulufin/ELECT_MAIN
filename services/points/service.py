# services/points/service.py

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, PermissionOverwrite, SelectOption, Thread

from firestores.fs_points import FS_Points

from services.points.constants import (
    REQUEST_CODE_PUBLIC,
    REQUEST_NOTE_PUBLIC,
    REQUEST_OP,
    REQUEST_POINT_PUBLIC,
    get_thread_info,
    get_use_option,
    parse_price_text,
)
from services.points.enums import Genre_Type, Points_Type
from services.points.helpers.formats import format_genre_totals
from services.points.ui.embeds import (
    Channel_Information_Embed,
    Create_Channel_Embed,
    Point_Request_Confirm_Check_Embed,
    Point_Request_Public_Embed,
    Points_Shortage_Embed,
    Points_Thread_Embed,
)
from utils.discord_helpers.user_ids import coerce_user_ids
from utils.discord_tasks.channel_message import safe_channel_send
from utils.discord_tasks.channels import safe_create_text_channel
from utils.discord_tasks.interaction import safe_followup_send
from utils.discord_tasks.threads import safe_create_tc_thread, safe_edit_tc_thread
from utils.ids import MAIN_CATEGORIES, MAIN_ROLES

logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo("Asia/Tokyo")


# =========================================================
# common helpers
# =========================================================

async def send_ephemeral_error(interaction: Interaction, content: str) -> None:
    await safe_followup_send(
        interaction=interaction,
        content=content,
        ephemeral=True,
    )


def build_points_meta(
    *,
    interaction: Interaction,
    code: str,
    price: int,
    target_user_ids: Iterable[int] | None = None,
    thread_id: int | None = None,
    channel_id: int | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "price": price,
        "executor_id": interaction.user.id,
        "target_user_ids": list(target_user_ids) if target_user_ids is not None else None,
        "thread_id": thread_id,
        "channel_id": channel_id,
        "guild_id": interaction.guild.id if interaction.guild else None,
    }


def build_mentions(*, user_ids: Iterable[int], role_ids: Iterable[int]) -> str:
    user_mentions = [f"<@{uid}>" for uid in user_ids]
    role_mentions = [f"<@&{rid}>" for rid in role_ids]
    return " ".join(user_mentions + role_mentions)


def parse_points_footer(embed: discord.Embed) -> tuple[list[int], str, str]:
    """
    footer format:
    role_id_1 / role_id_2 / op_value / pt_type
    """
    footer_text = embed.footer.text or ""
    footer_list = footer_text.strip(" / ").split(" / ")

    if len(footer_list) < 4:
        raise ValueError("footer format is invalid")

    role_ids = [int(footer_list[0]), int(footer_list[1])]
    op_value = footer_list[2]
    pt_type = footer_list[3]
    return role_ids, op_value, pt_type


def get_request_option(value: str) -> SelectOption | None:
    for option in REQUEST_OP:
        if option.value == value:
            return option
    return None


def build_private_channel_overwrites(
    *,
    guild: discord.Guild,
    user: discord.abc.User,
    admin_role: discord.Role,
    member_role: discord.Role,
    p_member_role: discord.Role,
) -> dict[Any, PermissionOverwrite]:
    return {
        guild.default_role: PermissionOverwrite(view_channel=False),
        admin_role: PermissionOverwrite(view_channel=True),
        user: PermissionOverwrite(
            view_channel=True,
            manage_roles=True,
            manage_channels=True,
            manage_messages=True,
        ),
        member_role: PermissionOverwrite(view_channel=False),
        p_member_role: PermissionOverwrite(view_channel=False),
    }


async def fetch_guild_resources(
    guild: discord.Guild,
) -> tuple[discord.abc.GuildChannel, discord.Role, discord.Role, discord.Role]:
    category = guild.get_channel(MAIN_CATEGORIES.PRIVATE_TC)
    if category is None:
        category = await guild.fetch_channel(MAIN_CATEGORIES.PRIVATE_TC)

    admin = guild.get_role(MAIN_ROLES.ADMINISTRATOR_ONE)
    if admin is None:
        admin = await guild.fetch_role(MAIN_ROLES.ADMINISTRATOR_ONE)

    member = guild.get_role(MAIN_ROLES.MEMBER)
    if member is None:
        member = await guild.fetch_role(MAIN_ROLES.MEMBER)

    p_member = guild.get_role(MAIN_ROLES.P_MEMBER)
    if p_member is None:
        p_member = await guild.fetch_role(MAIN_ROLES.P_MEMBER)

    return category, admin, member, p_member


def build_points_result_embed(
    *,
    total: int,
    genres: list[dict[str, int | str]],
    period_label: str,
) -> Embed:
    embed = Embed(
        title="__ポイント確認 - 結果__",
        description=f"期間：{period_label}",
    )
    embed.add_field(name="__全体__", value=f"{int(total):,} pt", inline=False)

    if not genres:
        embed.add_field(name="__内訳__", value="（該当なし）", inline=False)
        return embed

    for g in genres:
        name = str(g["name"])
        points = int(g["points"])
        embed.add_field(name=f"__{name}__", value=f"{points:,} pt", inline=True)

    return embed


# =========================================================
# request
# =========================================================

async def record_public_play_points(
    *,
    interaction: Interaction,
    user_ids: Sequence[int],
    fs_points: FS_Points,
) -> None:
    if not user_ids:
        await send_ephemeral_error(interaction, "対象ユーザーが見つかりませんでした。")
        return

    thread_id = interaction.channel.id if interaction.channel else None
    now = datetime.now(TIMEZONE)

    for uid in user_ids:
        await fs_points.record_event(
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

    await safe_followup_send(
        interaction=interaction,
        content="ポイントを付与しました。",
        ephemeral=True,
    )


async def create_public_request_thread(
    *,
    interaction: Interaction,
    selected_users: Sequence[discord.abc.User],
    selected_value: str,
    thread_view: discord.ui.View | None = None,
) -> None:
    if not selected_users:
        await send_ephemeral_error(interaction, "ユーザーが選択されていません。")
        return

    if interaction.channel is None:
        await send_ephemeral_error(interaction, "チャンネル情報の取得に失敗しました。")
        return

    selected_option = get_request_option(selected_value)
    if selected_option is None:
        await send_ephemeral_error(interaction, "申請項目の取得に失敗しました。")
        return

    use_point = parse_price_text(selected_option.description or str(REQUEST_POINT_PUBLIC))
    pt_type = selected_option.label

    user_ids = sorted({
        interaction.user.id,
        *(user.id for user in selected_users),
    })
    role_ids = [
        MAIN_ROLES.ADMINISTRATOR_ONE,
        MAIN_ROLES.ADMINISTRATOR_TWO,
    ]
    mentions = build_mentions(user_ids=user_ids, role_ids=role_ids)

    thread = await safe_create_tc_thread(
        channel=interaction.channel,
        name=f"🔞PL-{interaction.user.display_name}",
        private=True,
        invitable=False,
        use_queue=True,
    )

    if thread is None:
        await send_ephemeral_error(interaction, "スレッドの作成に失敗しました。")
        return

    await safe_channel_send(
        channel=thread,
        content=mentions,
        embed=Point_Request_Public_Embed(
            use_point=use_point,
            pt_type=pt_type,
        ),
        view=thread_view,
    )

    await safe_followup_send(
        interaction=interaction,
        content="申請用スレッドを作成しました。",
        ephemeral=True,
    )

async def open_public_request_review(
    *,
    interaction: Interaction,
    message_content: str,
    confirm_view: discord.ui.View | None = None,
) -> None:
    user_ids = sorted(coerce_user_ids(message_content or ""))
    mention_list = "\n".join(f"<@{uid}>" for uid in user_ids)

    await safe_followup_send(
        interaction=interaction,
        embed=Point_Request_Confirm_Check_Embed(mention_list=mention_list),
        view=confirm_view,
        ephemeral=True,
    )


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

    embed = build_points_result_embed(
        total=total,
        genres=genres,
        period_label=label,
    )

    await safe_followup_send(
        interaction=interaction,
        embed=embed,
        ephemeral=True,
    )


# =========================================================
# use
# =========================================================

async def consume_points_and_open_destination(
    *,
    interaction: Interaction,
    selected_option: SelectOption,
    fs_points: FS_Points,
    thread_view: discord.ui.View | None = None,
) -> None:
    guild = interaction.guild
    if guild is None:
        await send_ephemeral_error(interaction, "Guild情報の取得に失敗しました。")
        return

    if interaction.channel is None:
        await send_ephemeral_error(interaction, "チャンネル情報の取得に失敗しました。")
        return

    use_points = parse_price_text(selected_option.description or "0")

    summary = await fs_points.get_summary(user_id=interaction.user.id)
    total = int((summary or {}).get("total_points", 0) or 0)

    if use_points > total:
        await safe_followup_send(
            interaction=interaction,
            embed=Points_Shortage_Embed(
                user=interaction.user,
                total=total,
                use_points=use_points,
            ),
            ephemeral=True,
        )
        return

    try:
        thread_prefix, thread_title, event_type = get_thread_info(selected_option.value)
    except ValueError:
        await send_ephemeral_error(interaction, "利用項目の設定が見つかりません。")
        return

    group_code = selected_option.value.split("-")[0]

    if group_code != "02":
        thread = await safe_create_tc_thread(
            channel=interaction.channel,
            name=f"{thread_prefix}-{interaction.user.display_name}",
            invitable=False,
            private=True,
            use_queue=True,
        )

        if thread is None:
            await send_ephemeral_error(interaction, "スレッドの作成に失敗しました。")
            return

        await safe_followup_send(
            interaction=interaction,
            embed=Create_Channel_Embed(jump_url=thread.jump_url),
            ephemeral=True,
        )

        await safe_channel_send(
            channel=thread,
            content=f"{interaction.user.mention} <@&{MAIN_ROLES.ADMINISTRATOR_ONE}>",
            embed=Points_Thread_Embed(
                user=interaction.user,
                title=thread_title,
                selected=selected_option.label,
                use_points=use_points,
                op_value=selected_option.value,
                pt_type=event_type,
            ),
            view=thread_view,
        )
        return

    category, admin, member, p_member = await fetch_guild_resources(guild)

    tc = await safe_create_text_channel(
        guild=guild,
        category=category,
        name=interaction.user.display_name,
        overwrites=build_private_channel_overwrites(
            guild=guild,
            user=interaction.user,
            admin_role=admin,
            member_role=member,
            p_member_role=p_member,
        ),
    )

    if tc is None:
        await send_ephemeral_error(interaction, "チャンネルの作成に失敗しました。")
        return

    now = datetime.now(TIMEZONE)

    await fs_points.record_event(
        user_id=interaction.user.id,
        event_type=event_type,
        genre=Genre_Type.USE,
        delta=-use_points,
        note=selected_option.label,
        ts=now,
        meta=build_points_meta(
            interaction=interaction,
            code=selected_option.value,
            price=use_points,
            channel_id=tc.id,
        ),
    )

    await safe_followup_send(
        interaction=interaction,
        embed=Create_Channel_Embed(jump_url=tc.jump_url),
        ephemeral=True,
    )

    await safe_channel_send(
        channel=tc,
        embed=Channel_Information_Embed(),
    )

async def confirm_thread_point_use(
    *,
    interaction: Interaction,
    fs_points: FS_Points,
) -> None:
    msg = interaction.message
    if msg is None or not msg.embeds:
        await send_ephemeral_error(interaction, "メッセージ情報の取得に失敗しました。")
        return

    embed = msg.embeds[0]

    try:
        user_id = int(embed.author.name)
        role_ids, op_value, pt_type = parse_points_footer(embed)
    except (ValueError, TypeError):
        await send_ephemeral_error(interaction, "埋め込み情報の読み取りに失敗しました。")
        return

    if not any(role.id in role_ids for role in interaction.user.roles):
        await send_ephemeral_error(interaction, "これは管理者専用ボタンです。")
        return

    option = get_use_option(op_value)
    if option is None:
        await send_ephemeral_error(interaction, "利用項目の取得に失敗しました。")
        return

    use_points = parse_price_text(option.description or "0")
    now = datetime.now(TIMEZONE)

    await fs_points.record_event(
        user_id=user_id,
        event_type=pt_type,
        genre=Genre_Type.USE,
        delta=-use_points,
        note=option.label,
        ts=now,
        meta=build_points_meta(
            interaction=interaction,
            code=op_value,
            price=use_points,
            thread_id=interaction.channel.id if interaction.channel else None,
        ),
    )

    await safe_followup_send(
        interaction=interaction,
        content="ポイント利用を確定しました。",
        ephemeral=True,
    )


# =========================================================
# thread
# =========================================================

async def close_current_thread(*, interaction: Interaction) -> None:
    thread = interaction.channel
    if not isinstance(thread, Thread):
        await send_ephemeral_error(interaction, "スレッドでのみ実行できます。")
        return

    guild = interaction.guild
    if guild is None:
        await send_ephemeral_error(interaction, "Guild情報の取得に失敗しました。")
        return

    # 除外対象ロール
    allowed_role_ids = {
        MAIN_ROLES.ADMINISTRATOR_ONE,
        MAIN_ROLES.ADMINISTRATOR_TWO,
    }

    try:
        members = thread.members

        for member in members:
            # Botは除外
            if member.bot:
                continue

            # 指定ロール持ちは除外
            if any(role.id in allowed_role_ids for role in member.roles):
                continue

            try:
                await thread.remove_user(member)
            except Exception:
                logger.exception(f"thread.remove_user failed: {member.id}")

    except Exception:
        logger.exception("thread member iteration failed")

    await safe_edit_tc_thread(thread=thread, archived=True)

    await safe_followup_send(
        interaction=interaction,
        content="スレッドを閉じました。",
        ephemeral=True,
    )