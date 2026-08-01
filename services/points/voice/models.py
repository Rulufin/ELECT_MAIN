from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

_JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class TimedBoost:
    """期間限定ポイントブースト。start_dt 以上 end_dt 未満の間だけ有効。"""
    start_dt: datetime  # JST aware
    end_dt: datetime    # JST aware
    connect_point: Optional[int] = None
    connect_block_minutes: Optional[int] = None
    limit_minutes: Optional[int] = None
    owner_bonus_point: Optional[int] = None
    owner_threshold_min: Optional[int] = None

    def is_active(self, now: datetime) -> bool:
        now_jst = now.astimezone(_JST)
        return self.start_dt <= now_jst < self.end_dt


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
    timed_boosts: Tuple[TimedBoost, ...] = ()

    def has_owner_bonus(self) -> bool:
        return (
            self.owner_bonus_point is not None
            and self.owner_bonus_point > 0
            and self.owner_threshold_min is not None
            and self.owner_threshold_min > 0
        )

    def resolve(self, now: datetime) -> "VC_Point_Rule":
        """
        now に対してアクティブな TimedBoost を探し、
        マッチしたら該当フィールドを上書きしたルールを返す。
        マッチしなければ self をそのまま返す。
        """
        for boost in self.timed_boosts:
            if boost.is_active(now):
                overrides = {
                    k: v for k, v in {
                        "connect_point": boost.connect_point,
                        "connect_block_minutes": boost.connect_block_minutes,
                        "limit_minutes": boost.limit_minutes,
                        "owner_bonus_point": boost.owner_bonus_point,
                        "owner_threshold_min": boost.owner_threshold_min,
                    }.items()
                    if v is not None
                }
                if overrides:
                    return replace(self, **overrides, timed_boosts=())
        return self
