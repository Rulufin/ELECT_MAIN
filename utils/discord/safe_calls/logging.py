# utils/discord/logging.py
from __future__ import annotations

import logging
from typing import Any, Optional

import discord

from .errors import format_http_exception

logger = logging.getLogger(__name__)


def log_exception(
    exc: Exception,
    *,
    action: str,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    base = f"[discord] action={action}"
    if guild_id:
        base += f" guild={guild_id}"
    if channel_id:
        base += f" channel={channel_id}"
    if user_id:
        base += f" user={user_id}"
    logger.error(f"{base} err={format_http_exception(exc)}", exc_info=True)
