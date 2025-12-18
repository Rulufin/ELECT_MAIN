from dataclasses import dataclass
from typing import Optional, Literal
from discord import (
    Member, Guild, VoiceState, VoiceChannel, 
)
from datetime import datetime

from on_event.on_voice.configs import TransitionKind, NOT_CONNECT_VC_IDS, MAIN_CATEGORIES, MAIN_CHANNELS

@dataclass
class VoiceStateContext:
    """on_voice_state_update 1回分の情報と判定結果をまとめたコンテキスト。"""
    member: Member
    guild: Guild
    now: datetime

    before: VoiceState
    after: VoiceState

    before_ch: Optional[VoiceChannel]
    after_ch: Optional[VoiceChannel]

    before_id: Optional[int]
    after_id: Optional[int]

    transition: TransitionKind

    before_excluded: bool
    after_excluded: bool

    from_knock_waiting: bool
    to_knock_waiting: bool

    from_knock_category: bool
    to_knock_category: bool

    # 「ノックカテゴリ内のあるVCから離れた」（切断 or 別VCへ移動）
    left_knock_vc: bool

@staticmethod
def _is_excluded_channel(ch_id: Optional[int]) -> bool:
    if ch_id is None:
        return False
    return ch_id in NOT_CONNECT_VC_IDS

def build_context(
    member: Member,
    before: VoiceState,
    after: VoiceState,
    now: datetime,
) -> Optional[VoiceStateContext]:
    """on_voice_state_update の生引数から、後続処理で使いやすいコンテキストを組み立てる。"""

    guild = member.guild
    if guild is None:
        return None

    before_ch = before.channel if isinstance(before.channel, VoiceChannel) else None
    after_ch = after.channel if isinstance(after.channel, VoiceChannel) else None

    before_id = before_ch.id if before_ch else None
    after_id = after_ch.id if after_ch else None

    # 変化種類を判定
    if before_ch is None and after_ch is not None:
        transition: TransitionKind = "JOIN"
    elif before_ch is not None and after_ch is None:
        transition = "LEAVE"
    elif before_ch is not None and after_ch is not None and before_ch.id != after_ch.id:
        transition = "MOVE"
    else:
        transition = "NONE"

    before_excluded = _is_excluded_channel(before_id)
    after_excluded = _is_excluded_channel(after_id)

    from_knock_waiting = (before_id == MAIN_CHANNELS.KNOCK_ROOM)
    to_knock_waiting = (after_id == MAIN_CHANNELS.KNOCK_ROOM)

    from_knock_category = bool(before_ch and before_ch.category_id == MAIN_CATEGORIES.KNOCK_CATEGORY)
    to_knock_category = bool(after_ch and after_ch.category_id == MAIN_CATEGORIES.KNOCK_CATEGORY)

    left_knock_vc = False
    if from_knock_category and (after_ch is None or (after_ch and after_ch.id != before_ch.id)):
        # ノックカテゴリ内の「あるVC」から離れた
        left_knock_vc = True

    return VoiceStateContext(
        member=member,
        guild=guild,
        now=now,
        before=before,
        after=after,
        before_ch=before_ch,
        after_ch=after_ch,
        before_id=before_id,
        after_id=after_id,
        transition=transition,
        before_excluded=before_excluded,
        after_excluded=after_excluded,
        from_knock_waiting=from_knock_waiting,
        to_knock_waiting=to_knock_waiting,
        from_knock_category=from_knock_category,
        to_knock_category=to_knock_category,
        left_knock_vc=left_knock_vc,
    )