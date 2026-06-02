# utils/discord_tasks/queued_call.py
from __future__ import annotations

from typing import Awaitable, Callable, Optional, TypeVar

from queuemanager.discord.api import discord_queue
from utils.discord.safe_calls.buckets import BucketPair
from utils.discord.safe_calls.errors import RateLimitInfo

T = TypeVar("T")
CoroFactory = Callable[[], Awaitable[T]]

# 429が長いときにユーザーへ通知するためのコールバック
RateLimitNotifier = Callable[[RateLimitInfo], Awaitable[None]]


async def queued_call(
    coro_factory: CoroFactory[T],
    *,
    bucket: BucketPair,
    priority: int = 1,
    # ---- rate limit通知用メタ ----
    route: str | None = None,
    bucket_key: str | None = None,
    notifier: Optional[RateLimitNotifier] = None,
    notify_threshold: float = 15.0,
) -> T:
    """
    DiscordQueueManager へ enqueue する共通関数。
    - priority: 0 = 優先（Interaction followup/edit）, 1 = 通常（default）
    """
    return await discord_queue.enqueue(
        coro_factory,
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        priority=priority,
        route=route,
        bucket_key=bucket_key,
        on_rate_limit=notifier,
        notify_threshold=notify_threshold,
    )
