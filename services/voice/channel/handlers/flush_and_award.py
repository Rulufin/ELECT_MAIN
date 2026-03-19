from __future__ import annotations

import asyncio
import discord

from typing import Awaitable

from services.rank_system.voice_points import seconds_to_points
from services.rank_system.notifier import notify_vc_points
from services.rank_system._rank_config import resolve_vc_rule

from ..context import VoiceChannelContext


async def _resolve_user(guild: discord.Guild, user_id: int) -> discord.abc.User:
    m = guild.get_member(int(user_id))
    if m is not None:
        return m
    try:
        return await guild.fetch_member(int(user_id))
    except Exception:
        return discord.Object(id=int(user_id))  # type: ignore


async def flush_and_award_on_voice_delete(
    bot: discord.Client,
    channel: discord.abc.GuildChannel,
    ctx: VoiceChannelContext,
) -> None:
    # Voice / Stage 以外は無視
    if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return

    # VC稼働ルールで除外（enabled=False なら何もしない）
    rule = resolve_vc_rule(channel)
    if not rule.enabled:
        return

    vc_id = int(channel.id)
    guild = channel.guild
    guild_id = int(guild.id)

    # VC全体倍率（0や負は安全のため 1.0 扱い）
    multiplier = float(rule.multiplier or 1.0)
    if multiplier <= 0:
        multiplier = 1.0

    # 1) VCログ確定（倍率込み seconds を返す想定）
    user_seconds = await ctx.fs_voice_log.flush_by_vc_id(
        guild_id=guild_id,
        vc_id=vc_id,
        delete_docs=True,
    )
    if not user_seconds:
        return

    # 2) 秒→ポイント化 & 3) FS_Rankへ加算
    add_coros: list[Awaitable[None]] = []

    # notifier に渡す： (user, gained_points, raw_seconds, weighted_seconds)
    awarded_users: list[tuple[discord.abc.User, int, float, float]] = []

    total_weighted_seconds = 0.0
    total_raw_seconds = 0.0
    total_points = 0

    for user_id, weighted_sec in user_seconds.items():
        w = float(weighted_sec)
        if w <= 0:
            continue

        # weighted -> raw を逆算（VC全体倍率前提）
        raw_sec = w / multiplier

        gained = seconds_to_points(
            w,  # ★ポイント化は weighted 秒で行う（現状設計どおり）
            seconds_per_point=int(ctx.vc_seconds_per_point),
            round_up=bool(ctx.vc_round_up),
        )
        if gained <= 0:
            continue

        total_weighted_seconds += w
        total_raw_seconds += raw_sec
        total_points += int(gained)

        add_coros.append(
            ctx.fs_rank.add_vc_points(user_id=int(user_id), add=int(gained))
        )

        u = await _resolve_user(guild, int(user_id))
        awarded_users.append((u, int(gained), float(raw_sec), float(w)))

    if not awarded_users:
        return

    if add_coros:
        await asyncio.gather(*add_coros)

    # 4) まとめ通知（ユーザー別内訳 + 倍率 + 秒の整合確認）
    await notify_vc_points(
        bot=bot,
        guild_id=guild_id,
        vc_id=vc_id,
        awards=awarded_users,
        multiplier=multiplier,
        total_raw_seconds=total_raw_seconds,
        total_weighted_seconds=total_weighted_seconds,
        max_lines=int(ctx.max_bulk_lines),
    )
