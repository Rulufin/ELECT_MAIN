# services/points/post/configs.py

from dataclasses import dataclass

from services.points.enums import Genre_Type, Points_Type
from utils.ids import MAIN_CHANNELS


@dataclass(frozen=True)
class PostPointRule:
    point: int
    note: str
    event_type: Points_Type
    genre: Genre_Type


POST_POINT_RULES: dict[int, PostPointRule] = {
    MAIN_CHANNELS.VOICE_APPEAL: PostPointRule(
        point=30,
        note="ボイスアピール投稿",
        event_type=Points_Type.VOICE_APPEAL,
        genre=Genre_Type.VOICE_APPEAL,
    ),
    MAIN_CHANNELS.VOICE_APPEAL_ADULT: PostPointRule(
        point=50,
        note="18禁ボイスアピール投稿",
        event_type=Points_Type.VOICE_APPEAL,
        genre=Genre_Type.VOICE_APPEAL,
    ),    
    MAIN_CHANNELS.PHOTO_ADULT: PostPointRule(
        point=50,
        note="18禁画像投稿",
        event_type=Points_Type.PHOTO,
        genre=Genre_Type.PHOTO,
    ),
}