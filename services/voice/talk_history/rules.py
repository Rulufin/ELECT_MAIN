# on_event/on_voice/talk_history/rules.py
from __future__ import annotations

from typing import Optional

import discord
from discord import Member, VoiceState
from discord.abc import GuildChannel

from .config import (
    DEFAULT_TALK_HISTORY_CONFIG,
    CATEGORY_TALK_HISTORY_CONFIGS,
    TalkHistoryConfig,
)


def resolve_talk_history_config(
    channel: Optional[GuildChannel] = None,
    config: Optional[TalkHistoryConfig] = None,
) -> TalkHistoryConfig:
    """
    使用する TalkHistoryConfig を解決する。

    優先順:
      1. 明示的に渡された config
      2. channel.category_id に対応するカテゴリ別設定
      3. DEFAULT_TALK_HISTORY_CONFIG
    """
    if config is not None:
        return config

    if channel is None:
        return DEFAULT_TALK_HISTORY_CONFIG

    category_id = getattr(channel, "category_id", None)
    if category_id is not None:
        override = CATEGORY_TALK_HISTORY_CONFIGS.get(int(category_id))
        if override is not None:
            return override

    return DEFAULT_TALK_HISTORY_CONFIG


def should_track_member(
    member: Member,
    config: Optional[TalkHistoryConfig] = None,
) -> bool:
    """
    話した履歴の追跡対象メンバーかどうか。

    判定:
      - enabled=False なら対象外
      - bot許可設定がなければ bot は除外
      - denied_role_ids を1つでも持っていれば除外
      - required_role_ids が設定されている場合は、そのいずれかを持っている必要あり
    """
    cfg = config or DEFAULT_TALK_HISTORY_CONFIG

    if not cfg.enabled:
        return False

    if member.bot and not cfg.allow_bots:
        return False

    role_ids = {int(role.id) for role in getattr(member, "roles", [])}

    if cfg.denied_role_ids and (role_ids & set(cfg.denied_role_ids)):
        return False

    if cfg.required_role_ids and not (role_ids & set(cfg.required_role_ids)):
        return False

    return True


def extract_voice_channel_id(channel: Optional[GuildChannel]) -> Optional[int]:
    """
    Voice / Stage の channel.id を返す。
    それ以外は None。
    """
    if channel is None:
        return None

    if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return int(channel.id)

    return None


def is_same_voice_channel(
    before_channel: Optional[GuildChannel],
    after_channel: Optional[GuildChannel],
) -> bool:
    """
    before / after が同じ Voice / Stage チャンネルかどうか。
    """
    before_id = extract_voice_channel_id(before_channel)
    after_id = extract_voice_channel_id(after_channel)

    if before_id is None or after_id is None:
        return False

    return int(before_id) == int(after_id)


def is_trackable_channel(
    channel: Optional[GuildChannel],
    config: Optional[TalkHistoryConfig] = None,
) -> bool:
    """
    このチャンネルを話した履歴の対象にするか。

    判定順:
      1. enabled=False なら対象外
      2. Voice / Stage 以外は対象外
      3. StageChannel が禁止なら対象外
      4. denied_channel_ids に含まれていたら対象外
      5. allowed_channel_ids が設定されている場合は、その中に含まれている必要あり
    """
    cfg = resolve_talk_history_config(channel, config)

    if not cfg.enabled:
        return False

    if channel is None:
        return False

    is_voice = isinstance(channel, discord.VoiceChannel)
    is_stage = isinstance(channel, discord.StageChannel)

    if not (is_voice or is_stage):
        return False

    if is_stage and not cfg.allow_stage_channel:
        return False

    channel_id = int(channel.id)

    if channel_id in cfg.denied_channel_ids:
        return False

    if cfg.allowed_channel_ids and channel_id not in cfg.allowed_channel_ids:
        return False

    return True


def _is_self_deaf(voice_state: VoiceState) -> bool:
    return bool(getattr(voice_state, "self_deaf", False))


def _is_self_mute(voice_state: VoiceState) -> bool:
    return bool(getattr(voice_state, "self_mute", False))


def resolve_countable_state(
    member: Member,
    voice_state: VoiceState,
    config: Optional[TalkHistoryConfig] = None,
) -> bool:
    """
    talk history 用の countable 判定。

    countable=True 条件:
      - enabled=True
      - メンバーが追跡対象
      - 対象VCにいる
      - allow_self_deaf=False の場合は self_deaf でない
      - allow_self_mute=False の場合は self_mute でない
    """
    channel = getattr(voice_state, "channel", None)
    cfg = resolve_talk_history_config(channel, config)

    if not cfg.enabled:
        return False

    if not should_track_member(member, cfg):
        return False

    if not is_trackable_channel(channel, cfg):
        return False

    if (not cfg.allow_self_deaf) and _is_self_deaf(voice_state):
        return False

    if (not cfg.allow_self_mute) and _is_self_mute(voice_state):
        return False

    return True