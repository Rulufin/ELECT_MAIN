# services/points/enums.py

from enum import StrEnum


class Points_Type(StrEnum):

    # VC
    NORMAL_VC_CONNECT = "Normal_VC_Connect"
    NORMAL_VC_OWNER = "Normal_VC_Owner"

    PUBLIC_VC_CONNECT = "Public_VC_Connect"
    PUBLIC_VC_OWNER = "Public_VC_Owner"

    # PLAY
    PUBLIC_PLAY = "Public_Play"

    # USER
    USER_EVENT = "UserEvent"
    VOICE_APPEAL = "VoiceAppeal"
    PHOTO = "Photo"

    # ADMIN
    PENALTY = "Penalty"
    ADJUST = "Adjust"

    # USE
    USE_ICON_EMOJI = "Use_Icon_Emoji"
    USE_PRIVATE_TC = "Use_Private_TC"

    USE_ROLE_CREATE = "Use_Role_Create"
    USE_ROLE_RENAME = "Use_Role_Rename"
    USE_ROLE_COLOR = "Use_Role_Color"
    USE_ROLE_STYLE = "Use_Role_Style"
    USE_ROLE_ICON = "Use_Role_Icon"

    USE_FUN_REQUEST = "Use_Fun_Request"


class Genre_Type(StrEnum):
    VC = "VC"
    PLAY = "PLAY"
    USER = "USER"
    VOICE_APPEAL = "VOICE_APPEAL"
    PHOTO = "PHOTO"
    ADMIN = "ADMIN"
    USE = "USE"