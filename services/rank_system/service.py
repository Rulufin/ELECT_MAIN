from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import discord

from firestores.fs_rank import FS_Rank
from services.rank_system._rank_config import (
    resolve_vc_rule, resolve_tc_rule, is_eligible, resolve_role_multiplier,
)
from services.rank_system.voice_points import SECONDS_PER_POINT, seconds_to_points
from services.rank_system.text_points import TextPointRule, calc_text_points

TC_COOLDOWN_SEC: int = 30  # 同一ユーザーへの付与間隔（秒）
_TC_RULE = TextPointRule()  # デフォルト: 15〜25pt, min_chars=3

logger = logging.getLogger(__name__)


@dataclass
class _VCSession:
    join_time: datetime
    guild_id: int
    channel_id: int
    multiplier: float
    mic_mute_ok: bool   # True = ミュートでも加算対象
    credited_points: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _due_points(session: _VCSession, now: datetime) -> int:
    elapsed = (now - session.join_time).total_seconds()
    return seconds_to_points(elapsed * session.multiplier, seconds_per_point=SECONDS_PER_POINT)


class VCRankService:
    """VCランクポイントのセッション管理・付与ロジック。

    - start_session / flush_session でセッションを管理する。
    - tick() を定期的に呼ぶことで累計ポイントを段階付与する。
    """

    def __init__(self, fs_rank: FS_Rank) -> None:
        self.fs_rank = fs_rank
        self._sessions: dict[int, _VCSession] = {}  # user_id → session

    # ─────────────────────────────────────────────────────────
    # session management
    # ─────────────────────────────────────────────────────────

    def _effective_multiplier(self, member: discord.Member, rule) -> float:
        base = max(float(rule.multiplier or 1.0), 0.0) or 1.0
        return base * resolve_role_multiplier(member, rule.role_multipliers)

    def start_session(
        self,
        member: discord.Member,
        channel: discord.abc.GuildChannel,
        at: Optional[datetime] = None,
    ) -> None:
        rule = resolve_vc_rule(channel)
        if not is_eligible(member, rule):
            return
        self._sessions[member.id] = _VCSession(
            join_time=at or _utcnow(),
            guild_id=int(member.guild.id),
            channel_id=int(channel.id),
            multiplier=self._effective_multiplier(member, rule),
            mic_mute_ok=bool(rule.mic_mute),
        )

    async def flush_session(self, user_id: int, now: Optional[datetime] = None) -> int:
        """残ポイントを付与してセッションを削除する。付与したポイント数を返す。"""
        session = self._sessions.pop(user_id, None)
        if session is None:
            return 0
        due = _due_points(session, now or _utcnow())
        to_grant = due - session.credited_points
        if to_grant > 0:
            await self.fs_rank.add_vc_points(user_id, to_grant)
        return max(to_grant, 0)

    def seed_guild(self, guild: discord.Guild, at: Optional[datetime] = None) -> None:
        """起動時などに、すでにVCにいるメンバーのセッションを初期化する。"""
        now = at or _utcnow()
        channels = [*guild.voice_channels, *guild.stage_channels]
        for channel in channels:
            rule = resolve_vc_rule(channel)
            if not rule.enabled:
                continue
            for member in channel.members:
                if member.bot:
                    continue
                self.start_session(member, channel, at=now)

    # ─────────────────────────────────────────────────────────
    # periodic tick (5分ごとにcogから呼ぶ)
    # ─────────────────────────────────────────────────────────

    async def tick(self, bot: discord.Client) -> None:
        """5分ごとに差分ポイントを加算する。cogのtasks.loopから呼ぶ。"""
        now = _utcnow()
        for user_id, session in list(self._sessions.items()):
            if not session.mic_mute_ok and _is_muted(bot, session, user_id):
                continue

            due = _due_points(session, now)
            to_grant = due - session.credited_points
            if to_grant > 0:
                session.credited_points += to_grant  # await 前に確定（flush との二重カウント防止）
                await self.fs_rank.add_vc_points(user_id, to_grant)

    # ─────────────────────────────────────────────────────────
    # voice state routing
    # ─────────────────────────────────────────────────────────

    async def handle_voice_state(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        before_ch = before.channel
        after_ch = after.channel

        if before_ch == after_ch:
            return  # ミュート/スピーカー切替のみ

        if before_ch is not None:
            await self.flush_session(member.id)

        if after_ch is not None:
            self.start_session(member, after_ch)


class TCRankService:
    """TCランクポイントのメッセージ付与ロジック。

    - メッセージごとに rule を解決し、クールダウンを挟みながら付与する。
    - クールダウンはインメモリ管理（再起動でリセット）。
    """

    def __init__(self, fs_rank: FS_Rank) -> None:
        self.fs_rank = fs_rank
        self._cooldowns: dict[int, datetime] = {}  # user_id → last granted time

    def _effective_multiplier(self, member: discord.Member, rule) -> float:
        base = max(float(rule.multiplier or 1.0), 0.0) or 1.0
        return base * resolve_role_multiplier(member, rule.role_multipliers)

    async def handle_message(self, message: discord.Message) -> int:
        """1メッセージに対してTCポイントを付与する。付与したポイント数を返す。"""
        member = message.author
        if not isinstance(member, discord.Member):
            return 0

        channel = message.channel
        if not isinstance(channel, discord.abc.GuildChannel):
            return 0

        rank_rule = resolve_tc_rule(channel)
        if not is_eligible(member, rank_rule):
            return 0

        # クールダウンチェック
        now = _utcnow()
        last = self._cooldowns.get(member.id)
        if last is not None and (now - last).total_seconds() < TC_COOLDOWN_SEC:
            return 0

        # ランダムポイント計算（15〜25pt, 3文字未満は0）
        base = calc_text_points(message.content or "", rule=_TC_RULE)
        if base == 0:
            return 0

        # カテゴリ・ロール倍率を適用
        mult = self._effective_multiplier(member, rank_rule)
        points = max(1, int(base * mult))

        self._cooldowns[member.id] = now  # await 前に確定（連打二重付与防止）
        await self.fs_rank.add_tc_points(member.id, points)
        return points


def _is_muted(bot: discord.Client, session: _VCSession, user_id: int) -> bool:
    guild = bot.get_guild(session.guild_id)
    if guild is None:
        return False
    member = guild.get_member(user_id)
    if member is None or member.voice is None:
        return False
    return bool(member.voice.self_mute or member.voice.mute)
