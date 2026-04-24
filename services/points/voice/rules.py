from typing import Mapping

from utils.ids import MAIN_CATEGORIES
from .enums import VCType
from .models import VC_Point_Rule

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