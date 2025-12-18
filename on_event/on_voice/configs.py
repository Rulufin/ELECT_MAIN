# config.py
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal

from utils.ids import MAIN_CHANNELS, MAIN_CATEGORIES

FILENAME = "on_voice_state_main"
TIMEZONE = ZoneInfo("Asia/Tokyo")

TIMEZONE = ZoneInfo("Asia/Tokyo")

# 接続判定から除外するVC
NOT_CONNECT_VC_IDS = [
    MAIN_CHANNELS.PUBLIC,
    MAIN_CHANNELS.FREE_ROOM,
    MAIN_CHANNELS.QM,
    MAIN_CHANNELS.S_QM_MALE,
    MAIN_CHANNELS.S_QM_FEMALE,
    MAIN_CHANNELS.ROOM,
    MAIN_CHANNELS.SLEEP_VC,
    MAIN_CHANNELS.KNOCK_ROOM,
]

TransitionKind = Literal["JOIN", "LEAVE", "MOVE", "NONE"]
