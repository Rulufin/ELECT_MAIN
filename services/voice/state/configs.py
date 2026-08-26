from zoneinfo import ZoneInfo
from typing import Literal

from utils.ids import MAIN_CHANNELS, MAIN_CATEGORIES

FILENAME = "on_voice_state_main"
TIMEZONE = ZoneInfo("Asia/Tokyo")

NOT_CONNECT_VC_IDS = [
    MAIN_CHANNELS.PUBLIC,
    MAIN_CHANNELS.FREE_ROOM,
    MAIN_CHANNELS.QM,
    MAIN_CHANNELS.ROOM,
    MAIN_CHANNELS.SLEEP_VC,
    MAIN_CHANNELS.KNOCK_ROOM,
]

TransitionKind = Literal["JOIN", "LEAVE", "MOVE", "NONE"]
