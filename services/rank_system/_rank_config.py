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
    multiplier: 倍率
    mic_mute: True(計算にいれる) or False(計算にいれない)
    allow_role_ids: ロール所持者を対象にする
    deny_role_ids: ロール所持者を対象外にする
    ''' 
    enabled: bool = True
    multiplier: float = 1.0
    mic_mute: bool = True
    allow_role_ids: set[int] = field(default_factory=set)
    deny_role_ids: set[int] = field(default_factory=set)


VC_CATEGORY_RULES: dict[int, RankRule] = {

    MAIN_CATEGORIES.PUBLIC_QMs: RankRule(
        enabled=True,
        multiplier=1.0,
        mic_mute=True,
        deny_role_ids={MAIN_ROLES.P_MEMBER},
    ),
    MAIN_CATEGORIES.SECRET_ROOMs: RankRule(
        enabled=True,
        multiplier=0.5,
        mic_mute=True,
        deny_role_ids={MAIN_ROLES.P_MEMBER},
    ),
    MAIN_CATEGORIES.SUB_SECRET_ROOMs: RankRule(
        enabled=True,
        multiplier=0.5,
        mic_mute=True,
        deny_role_ids={MAIN_ROLES.P_MEMBER},
    ),
    MAIN_CATEGORIES.PUBLIC_PLAYs: RankRule(
        enabled=True,
        multiplier=5.0,
        mic_mute=False,
    ),

    # 無効
    MAIN_CATEGORIES.WELCOMEs: RankRule(enabled=False),
    MAIN_CATEGORIES.TALK_ROOM_CREATEs: RankRule(enabled=False),
    MAIN_CATEGORIES.FREE_ROOM_CREATEs: RankRule(enabled=False),
    MAIN_CATEGORIES.PUBLIC_QM_CREATEs: RankRule(enabled=False),
    MAIN_CATEGORIES.PUBLIC_ROOM_CREATEs: RankRule(enabled=False),
}

VC_CHANNEL_RULES: dict[int, RankRule] = {
    # vc_id: RankRule(enabled=False),
}

# services/rank_system/rank_config.py に追記（VC用と同居でOK）

TC_CATEGORY_RULES: dict[int, RankRule] = {
    MAIN_CATEGORIES.PUBLIC_PLAYs: RankRule(
        enabled=True,
        multiplier=2
    ),

    MAIN_CATEGORIES.MANAGEMENT: RankRule(enabled=False),
    MAIN_CATEGORIES.ASSISTANT: RankRule(enabled=False),
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



