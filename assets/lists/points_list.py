from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Optional, Tuple

from utils.ids import MAIN_CATEGORIES


class VCType(StrEnum):
    NORMAL = "normal"
    PUBLIC_ROOM = "public_room"
    SECRET_ROOM = "secret_room"


@dataclass(frozen=True)
class VC_Point_Rule:
    # ─────────────
    # Connect points
    # ─────────────
    connect_block_minutes: int
    connect_point: int
    limit_minutes: Optional[int] = None

    # ─────────────
    # Owner bonus
    # ─────────────
    owner_bonus_point: Optional[int] = None
    owner_threshold_min: Optional[int] = None

    # ─────────────
    # Mute policy
    # True: カウントする（ポイント対象）
    # False: 除外する（ポイント対象外）
    # ─────────────
    include_mic_mute: bool = True
    include_speaker_mute: bool = True

    # ─────────────
    # Category mapping
    # ─────────────
    category_ids: Tuple[int, ...] = ()

    def has_owner_bonus(self) -> bool:
        return (
            self.owner_bonus_point is not None
            and self.owner_bonus_point > 0
            and self.owner_threshold_min is not None
            and self.owner_threshold_min > 0
        )


VC_POINT_RULES: Mapping[VCType, VC_Point_Rule] = {
    VCType.NORMAL: VC_Point_Rule(
        connect_block_minutes=15,
        connect_point=10,
        limit_minutes=None,
        owner_bonus_point=30,
        owner_threshold_min=10,

        include_mic_mute=False,
        include_speaker_mute=False,

        category_ids=(MAIN_CATEGORIES.FREE_CATEGORY, MAIN_CATEGORIES.KNOCK_CATEGORY),
    ),
    VCType.PUBLIC_ROOM: VC_Point_Rule(
        connect_block_minutes=30,
        connect_point=30,
        limit_minutes=480,
        owner_bonus_point=None,
        owner_threshold_min=None,

        include_mic_mute=True,
        include_speaker_mute=False,

        category_ids=(MAIN_CATEGORIES.PUBLIC_QM, MAIN_CATEGORIES.PUBLIC_ROOM),
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
