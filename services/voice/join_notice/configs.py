from __future__ import annotations

from dataclasses import dataclass, field

from utils.ids import MAIN_CHANNELS, MAIN_CATEGORIES


@dataclass(frozen=True)
class JoinNoticeHandlerConfig:
    enabled: bool = True

    # 明示許可
    allow_vc_ids: set[int] = field(default_factory=set)
    allow_category_ids: set[int] = field(default_factory=set)

    # 明示除外
    exclude_vc_ids: set[int] = field(default_factory=set)
    exclude_category_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class JoinNoticeSystemConfig:
    enabled_handlers: set[str] = field(default_factory=set)


ENABLED_JOIN_NOTICE_HANDLERS: tuple[str, ...] = (
    "ProfileJoinNoticeHandler",
    # "OtherJoinNoticeHandler",
)

JOIN_NOTICE_HANDLER_CONFIGS: dict[str, JoinNoticeHandlerConfig] = {
    "ProfileJoinNoticeHandler": JoinNoticeHandlerConfig(
        enabled=True,
        allow_vc_ids=set(),
        allow_category_ids=set(),
        exclude_vc_ids={
            MAIN_CHANNELS.PUBLIC, MAIN_CHANNELS.FREE_ROOM,
            MAIN_CHANNELS.QM, MAIN_CHANNELS.S_QM_MALE, MAIN_CHANNELS.S_QM_FEMALE,
            MAIN_CHANNELS.ROOM, MAIN_CHANNELS.KNOCK_ROOM,
            MAIN_CHANNELS.SLEEP_VC
        },
        exclude_category_ids={
            1424277873463787550, # 入場カテゴリ
            1424002470509805668, # 管理カテゴリ
            1423782520322789407, # 公開カテゴリ
        },
    ),
}