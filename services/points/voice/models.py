from dataclasses import dataclass
from typing import Optional, Tuple

@dataclass(frozen=True)
class VC_Point_Rule:
    connect_block_minutes: int
    connect_point: int
    limit_minutes: Optional[int] = None

    owner_bonus_point: Optional[int] = None
    owner_threshold_min: Optional[int] = None

    include_mic_mute: bool = True
    include_speaker_mute: bool = True

    category_ids: Tuple[int, ...] = ()

    def has_owner_bonus(self) -> bool:
        return (
            self.owner_bonus_point is not None
            and self.owner_bonus_point > 0
            and self.owner_threshold_min is not None
            and self.owner_threshold_min > 0
        )