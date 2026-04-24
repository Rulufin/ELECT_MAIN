from __future__ import annotations

from services.voice.join_notice.configs import ENABLED_JOIN_NOTICE_HANDLERS
from services.voice.join_notice.profile_notice import ProfileJoinNoticeHandler


HANDLER_REGISTRY = {
    "ProfileJoinNoticeHandler": ProfileJoinNoticeHandler,
    # "OtherJoinNoticeHandler": OtherJoinNoticeHandler,
}


def build_join_notice_handlers() -> list:
    handlers = []

    for handler_name in ENABLED_JOIN_NOTICE_HANDLERS:
        handler_cls = HANDLER_REGISTRY.get(handler_name)
        if handler_cls is None:
            continue

        handlers.append(handler_cls())

    return handlers