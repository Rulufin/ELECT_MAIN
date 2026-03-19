# utils/discord/typing.py
from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")
CoroFactory = Callable[[], Awaitable[T]]
