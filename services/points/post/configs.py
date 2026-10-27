# services/points/post/configs.py

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Tuple
from zoneinfo import ZoneInfo

from services.points.enums import Genre_Type, Points_Type
from utils.ids import MAIN_CHANNELS

_JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class PostTimedBoost:
    """期間限定ポイントブースト。start_dt 以上 end_dt 未満の間だけ有効。"""
    start_dt: datetime
    end_dt: datetime
    point: int

    def is_active(self, now: datetime) -> bool:
        now_jst = now.astimezone(_JST)
        return self.start_dt <= now_jst < self.end_dt


@dataclass(frozen=True)
class PostPointRule:
    point: int
    note: str
    event_type: Points_Type
    genre: Genre_Type
    timed_boosts: Tuple[PostTimedBoost, ...] = field(default_factory=tuple)

    def resolve(self, now: datetime) -> "PostPointRule":
        for boost in self.timed_boosts:
            if boost.is_active(now):
                return replace(self, point=boost.point, timed_boosts=())
        return self


POST_POINT_RULES: dict[int, PostPointRule] = {
    MAIN_CHANNELS.VOICE_APPEAL: PostPointRule(
        point=30,
        note="ボイスアピール投稿",
        event_type=Points_Type.VOICE_APPEAL,
        genre=Genre_Type.VOICE_APPEAL,
        timed_boosts=(
            PostTimedBoost(
                start_dt=datetime(2026, 10, 28, 0, 0, tzinfo=_JST),
                end_dt=datetime(2026, 11, 2, 0, 0, tzinfo=_JST),  # 11/1 23:59 まで
                point=60,  # 通常 30pt → 60pt (2倍)
            ),
        ),
    ),
    MAIN_CHANNELS.VOICE_APPEAL_ADULT: PostPointRule(
        point=50,
        note="18禁ボイスアピール投稿",
        event_type=Points_Type.VOICE_APPEAL,
        genre=Genre_Type.VOICE_APPEAL,
        timed_boosts=(
            PostTimedBoost(
                start_dt=datetime(2026, 10, 28, 0, 0, tzinfo=_JST),
                end_dt=datetime(2026, 11, 2, 0, 0, tzinfo=_JST),  # 11/1 23:59 まで
                point=150,  # 通常 50pt → 150pt (3倍)
            ),
        ),
    ),    
    MAIN_CHANNELS.PHOTO_ADULT: PostPointRule(
        point=50,
        note="18禁画像投稿",
        event_type=Points_Type.PHOTO,
        genre=Genre_Type.PHOTO,
        timed_boosts=(
            PostTimedBoost(
                start_dt=datetime(2026, 10, 28, 0, 0, tzinfo=_JST),
                end_dt=datetime(2026, 11, 2, 0, 0, tzinfo=_JST),  # 11/1 23:59 まで
                point=150,  # 通常 50pt → 150pt (3倍)
            ),
        ),
    ),
    MAIN_CHANNELS.HAPPY_HALLOWEEN: PostPointRule(
        point=50,
        note="ハッピーハロウィン",
        event_type=Points_Type.PHOTO,
        genre=Genre_Type.PHOTO,
        timed_boosts=(
            PostTimedBoost(
                start_dt=datetime(2026, 10, 28, 0, 0, tzinfo=_JST),
                end_dt=datetime(2026, 11, 2, 0, 0, tzinfo=_JST),  # 11/1 23:59 まで
                point=150,  # 通常 50pt → 100pt (2倍)
            ),
        )
    )
}