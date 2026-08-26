from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import discord
from utils.ids import MAIN_CATEGORIES, MAIN_CHANNELS, MAIN_ROLES


@dataclass(frozen=True)
class RankRule:
    '''
    RankRule の Docstring
    ―――――――――――――――――――――――――
    enabled: True(稼働する) or False(稼働させない)
    multiplier: カテゴリ/チャンネル単位の倍率
    mic_mute: True(計算にいれる) or False(計算にいれない)
    allow_role_ids: ロール所持者を対象にする
    deny_role_ids: ロール所持者を対象外にする
    role_multipliers: ロールごとの倍率 {role_id: multiplier}
                      複数ロールが一致した場合は最小値を採用
                      空の場合は 1.0 (変化なし)
    '''
    enabled: bool = True
    multiplier: float = 1.0
    mic_mute: bool = True
    allow_role_ids: set[int] = field(default_factory=set)
    deny_role_ids: set[int] = field(default_factory=set)
    role_multipliers: dict[int, float] = field(default_factory=dict)


VC_CATEGORY_RULES: dict[int, RankRule] = {

    MAIN_CATEGORIES.FREE_CATEGORY: RankRule(
        enabled=True,
        multiplier=1.0,
        mic_mute=True,
    ),
    MAIN_CATEGORIES.KNOCK_CATEGORY: RankRule(
        enabled=True,
        multiplier=1.0,
        mic_mute=True,
    ),
    MAIN_CATEGORIES.PUBLIC_QM: RankRule(
        enabled=True,
        multiplier=1.0,
        mic_mute=True,
    ),
    MAIN_CATEGORIES.SECRET_QM: RankRule(
        enabled=True,
        multiplier=1.0,
        mic_mute=True,
    ),
    MAIN_CATEGORIES.PUBLIC_ROOM: RankRule(
        enabled=True,
        multiplier=1.0,
        mic_mute=True,
    ),
    MAIN_CATEGORIES.SECRET_ROOM: RankRule(
        enabled=True,
        multiplier=1.0,
        mic_mute=True,
    ),
    MAIN_CATEGORIES.PUBLIC_PLAY: RankRule(
        enabled=True,
        multiplier=5.0,
        mic_mute=False,
    ),

    # 無効
    MAIN_CATEGORIES.WELCOMEs: RankRule(enabled=False),
}

VC_CHANNEL_RULES: dict[int, RankRule] = {
    MAIN_CHANNELS.PUBLIC: RankRule(enabled=False),
    MAIN_CHANNELS.FREE_ROOM: RankRule(enabled=False),
    MAIN_CHANNELS.KNOCK_ROOM: RankRule(enabled=False),
    MAIN_CHANNELS.QM: RankRule(enabled=False),
    MAIN_CHANNELS.ROOM: RankRule(enabled=False),
    MAIN_CHANNELS.SLEEP_VC: RankRule(enabled=False)
}

# services/rank_system/rank_config.py に追記（VC用と同居でOK）

TC_CATEGORY_RULES: dict[int, RankRule] = {
    MAIN_CATEGORIES.PUBLIC_PLAY: RankRule(
        enabled=True,
        multiplier=2
    ),

    MAIN_CATEGORIES.MANAGEMENTs: RankRule(enabled=False),
    MAIN_CATEGORIES.WELCOMEs: RankRule(enabled=False),
    MAIN_CATEGORIES.INFORMATIONs: RankRule(enabled=False)
}

TC_CHANNEL_RULES: dict[int, RankRule] = {
    MAIN_CHANNELS.SLEEP_MENTION: RankRule(
        enabled=False
    ),
    MAIN_CHANNELS.PUBLIC_PLAY_ANNOUNCE: RankRule(
        enabled=False
    ),
    MAIN_CHANNELS.PUBLIC_ANNOUNCE: RankRule(
        enabled=False
    )
}


def resolve_vc_rule(ch: Optional[discord.abc.GuildChannel]) -> RankRule:
    if ch is None:
        return RankRule()
    r = VC_CHANNEL_RULES.get(int(ch.id))
    if r is not None:
        return r
    cat_id = getattr(ch, "category_id", None)
    if cat_id is None:
        return RankRule()
    return VC_CATEGORY_RULES.get(int(cat_id), RankRule())

def resolve_tc_rule(ch: Optional[discord.abc.GuildChannel]) -> RankRule:
    if ch is None:
        return RankRule()

    r = TC_CHANNEL_RULES.get(int(ch.id))
    if r is not None:
        return r

    cat_id = getattr(ch, "category_id", None)
    if cat_id is None:
        return RankRule()

    return TC_CATEGORY_RULES.get(int(cat_id), RankRule())

def is_eligible(member: discord.Member, rule: RankRule) -> bool:
    if not rule.enabled:
        return False

    role_ids = {r.id for r in member.roles}

    if rule.deny_role_ids and (role_ids & rule.deny_role_ids):
        return False

    if rule.allow_role_ids:
        return bool(role_ids & rule.allow_role_ids)

    return True


def resolve_role_multiplier(member: discord.abc.User, multipliers: dict[int, float]) -> float:
    """ロールごとの倍率を解決する。複数一致した場合は最小値を採用。
    Member 以外（退鯖済み等）は 1.0 を返す。"""
    if not multipliers or not isinstance(member, discord.Member):
        return 1.0
    role_ids = {r.id for r in member.roles}
    matches = [mult for role_id, mult in multipliers.items() if role_id in role_ids]
    return min(matches) if matches else 1.0



