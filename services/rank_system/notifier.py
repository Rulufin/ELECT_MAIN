# services/rank_system/notifier.py
from __future__ import annotations

import logging
import time
from typing import Optional

import discord

from utils.ids import MAIN_SERVER_ID, MAIN_CHANNELS

logger = logging.getLogger(__name__)


# =========================================================
# 固定設定
# =========================================================

POINTS_LOG_GUILD_ID: int = int(MAIN_SERVER_ID)
POINTS_LOG_CHANNEL_ID: int = int(MAIN_CHANNELS.LOG)

# 同一ユーザーのログ連投防止（秒）
PER_USER_COOLDOWN_SECONDS: float = 0.0


# =========================================================
# 内部クールダウン管理
# =========================================================

_last_log_at: dict[int, float] = {}


def _allow_user(user_id: int) -> bool:
    if PER_USER_COOLDOWN_SECONDS <= 0:
        return True

    now = time.time()
    last = _last_log_at.get(int(user_id))

    if last is None or (now - last) >= PER_USER_COOLDOWN_SECONDS:
        _last_log_at[int(user_id)] = now
        return True

    return False


# =========================================================
# Utility
# =========================================================

async def _resolve_channel(bot: discord.Client) -> Optional[discord.TextChannel]:
    ch = bot.get_channel(POINTS_LOG_CHANNEL_ID)
    if isinstance(ch, discord.TextChannel):
        return ch

    try:
        fetched = await bot.fetch_channel(POINTS_LOG_CHANNEL_ID)
    except Exception:
        return None

    return fetched if isinstance(fetched, discord.TextChannel) else None


def _fmt_delta(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def _fmt_mult(x: float) -> str:
    # x2.0 でも x2 でも見やすい方に寄せる
    try:
        if float(x).is_integer():
            return f"x{int(x)}"
    except Exception:
        pass
    return f"x{float(x):g}"


def _fmt_sec(x: float) -> str:
    # 小数は切り捨て表示（ログ用途なら int で十分）
    try:
        return f"{int(x)}"
    except Exception:
        return str(x)


# =========================================================
# Public API
# =========================================================

async def notify_tc_points(
    *,
    bot: discord.Client,
    guild_id: int,
    user: discord.abc.User,
    delta_tc: int = 0,
    delta_vc: int = 0,
    reason: str = "",
    extra: str = "",
) -> None:
    """
    固定ギルド・固定チャンネルにポイント付与ログを送る。
    """

    # 対象ギルド以外は無視
    if int(guild_id) != POINTS_LOG_GUILD_ID:
        return

    if delta_tc == 0 and delta_vc == 0:
        return

    if not _allow_user(int(user.id)):
        return

    channel = await _resolve_channel(bot)
    if channel is None:
        logger.warning("[notifier] log channel not found")
        return

    parts = []
    if delta_tc:
        parts.append(f"TC: `{_fmt_delta(int(delta_tc))}`")
    if delta_vc:
        parts.append(f"VC: `{_fmt_delta(int(delta_vc))}`")

    desc_lines = [
        f"対象: {user.mention}（`{user.id}`）",
        f"付与: {' / '.join(parts)}",
    ]

    if reason:
        desc_lines.append(f"理由: {reason}")
    if extra:
        desc_lines.append(f"詳細: {extra}")

    embed = discord.Embed(
        title="ポイント付与",
        description="\n".join(desc_lines),
    )

    try:
        await channel.send(embed=embed)
    except Exception:
        logger.exception("[notifier] failed to send log")


async def notify_vc_points(
    *,
    bot: discord.Client,
    guild_id: int,
    vc_id: int,
    # (user, gained_points, raw_seconds, weighted_seconds)
    awards: list[tuple[discord.abc.User, int, float, float]],
    multiplier: float = 1.0,
    total_raw_seconds: float | None = None,
    total_weighted_seconds: float | None = None,
    max_lines: int = 15,
) -> None:
    """
    VC削除時などの「まとめ通知」。
    awards: [(user, gained_points, raw_seconds, weighted_seconds), ...]
    """
    if int(guild_id) != POINTS_LOG_GUILD_ID:
        return
    if not awards:
        return

    channel = await _resolve_channel(bot)
    if channel is None:
        logger.warning("[notifier] log channel not found")
        return

    total_users = len(awards)

    # 表示行（倍率 / 生秒 / 加重秒 / pt を見える化）
    # 例: @user : 300s → 600s / `+10`
    lines = [
        f"{u.mention} : `{_fmt_sec(raw)}s` → `{_fmt_sec(weighted)}s` / `{_fmt_delta(int(p))}`"
        for u, p, raw, weighted in awards
    ]

    omitted = 0
    if max_lines > 0 and len(lines) > max_lines:
        omitted = len(lines) - max_lines
        lines = lines[:max_lines]

    desc = [
        f"VC: `{vc_id}`",
        f"倍率: `{_fmt_mult(float(multiplier or 1.0))}`",
        f"人数: `{total_users}`",
    ]

    # 合計秒（指定が無ければ awards から算出）
    if total_raw_seconds is None:
        total_raw_seconds = sum(raw for _, _, raw, _ in awards)
    if total_weighted_seconds is None:
        total_weighted_seconds = sum(weighted for _, _, _, weighted in awards)

    desc.append("")
    desc.append("**内訳（生秒 → 加重秒 / pt）**")
    desc.extend(lines)

    if omitted:
        desc.append(f"...（他 `{omitted}` 人省略）")

    embed = discord.Embed(
        title="VCポイント付与（まとめ）",
        description="\n".join(desc),
    )

    try:
        await channel.send(embed=embed)
    except Exception:
        logger.exception("[notifier] failed to send vc bulk log")
