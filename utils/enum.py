# utils/enum.py
from enum import StrEnum


class Points_Type(StrEnum):
    # ───── VC ─────
    NORMAL_VC_CONNECT = "Normal_VC_Connect"
    NORMAL_VC_OWNER = "Normal_VC_Owner"

    PUBLIC_VC_CONNECT = "Public_VC_Connect"
    PUBLIC_VC_OWNER = "Public_VC_Owner"

    # ───── PLAY / 公開 ─────
    PUBLIC_PLAY = "Public_Play"

    # ───── USER 系 ─────
    USER_EVENT = "UserEvent"
    PHOTO = "Photo"

    # ───── 管理 / 特殊 ─────
    PENALTY = "Penalty"
    ADJUST = "Adjust"

class Genre_Type(StrEnum):
    VC = "VC"
    PLAY = "PLAY"
    USER = "USER"
    PHOTO = "PHOTO"
    ADMIN = "ADMIN"