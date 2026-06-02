# utils/discord/queueing.py
from __future__ import annotations

from typing import Literal, Optional

MajorKind = Literal["guild", "channel", "webhook", "other"]


def bucket_route_major(method: str, route_template: str, *, major_kind: MajorKind, major_id: str | int) -> str:
    """
    A deterministic bucket key aligned with Discord's 'route + major parameter' concept.
    route_template should be a normalized template, e.g.:
      "/channels/{channel_id}/messages"
      "/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
      "/webhooks/{application_id}/{interaction_token}"
    """
    m = method.upper().strip()
    r = route_template.strip()
    return f"route:{m}:{r}|major:{major_kind}:{major_id}"


def serial_user(user_id: int) -> str:
    return f"user:{user_id}"


def serial_channel(channel_id: int) -> str:
    return f"channel:{channel_id}"


def serial_message(message_id: int) -> str:
    return f"message:{message_id}"
