# utils/discord_tasks/_missing.py
from __future__ import annotations

from typing import Any, Optional

from discord.utils import MISSING


def opt(value: Any) -> Any:
    """None を discord.utils.MISSING に変換して返す。"""
    return MISSING if value is None else value


def opt_list(value: Optional[list[Any]]) -> Any:
    """None を MISSING、空リストは空リストのまま。"""
    return MISSING if value is None else value
