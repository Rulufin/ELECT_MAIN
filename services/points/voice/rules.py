from datetime import datetime
from typing import Mapping
from zoneinfo import ZoneInfo

from utils.ids import MAIN_CATEGORIES
from .enums import VCType
from .models import TimedBoost, VC_Point_Rule

_JST = ZoneInfo("Asia/Tokyo")

VC_POINT_RULES: Mapping[VCType, VC_Point_Rule] = {
    VCType.NORMAL: VC_Point_Rule(
        connect_block_minutes=15,
        connect_point=10,
        limit_minutes=None,
        owner_bonus_point=30,
        owner_threshold_min=10,
        include_mic_mute=False,
        include_speaker_mute=False,
        category_ids=(
            MAIN_CATEGORIES.FREE_CATEGORY,
            MAIN_CATEGORIES.KNOCK_CATEGORY,
        ),
        timed_boosts=(
            TimedBoost(
                start_dt=datetime(2026, 10, 28, 0, 0, tzinfo=_JST),
                end_dt=datetime(2026, 11, 2, 0, 0, tzinfo=_JST),  # 11/1 23:59 まで
                connect_point=20,       # 通常 10pt → 20pt (2倍)
                owner_bonus_point=60,   # 通常 30pt → 60pt (2倍)
            ),
        ),
    ),
    VCType.PUBLIC_ROOM: VC_Point_Rule(
        connect_block_minutes=30,
        connect_point=30,
        limit_minutes=480,
        owner_bonus_point=None,
        owner_threshold_min=None,
        include_mic_mute=True,
        include_speaker_mute=False,
        category_ids=(
            MAIN_CATEGORIES.PUBLIC_QM,
            MAIN_CATEGORIES.PUBLIC_ROOM,
        ),
        timed_boosts=(
            TimedBoost(
                start_dt=datetime(2026, 10, 28, 0, 0, tzinfo=_JST),
                end_dt=datetime(2026, 11, 2, 0, 0, tzinfo=_JST),  # 11/1 23:59 まで
                connect_point=90,  # 通常 30pt → 90pt (3倍)
            ),
        ),
    ),
    VCType.SECRET_ROOM: VC_Point_Rule(
        connect_block_minutes=15,
        connect_point=10,
        limit_minutes=480,
        owner_bonus_point=None,
        owner_threshold_min=None,
        include_mic_mute=True,
        include_speaker_mute=False,
        category_ids=(
            MAIN_CATEGORIES.SECRET_QM,
            MAIN_CATEGORIES.SECRET_ROOM,
        ),
    ),
}