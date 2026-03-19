# utils/discord_tasks/queued_call.py
from __future__ import annotations

from typing import Awaitable, Callable, Optional, TypeVar

from queuemanagers.discord_queue_core import discord_queue
from utils.discord_tasks.buckets import BucketPair
from utils.discord_tasks.errors import RateLimitInfo

T = TypeVar("T")
CoroFactory = Callable[[], Awaitable[T]]

# 429が長いときにユーザーへ通知するためのコールバック
RateLimitNotifier = Callable[[RateLimitInfo], Awaitable[None]]


async def queued_call(
    coro_factory: CoroFactory[T],
    *,
    bucket: BucketPair,
    # ---- rate limit通知用メタ ----
    route: str | None = None,
    bucket_key: str | None = None,
    notifier: Optional[RateLimitNotifier] = None,
    notify_threshold: float = 15.0,
) -> T:
    """
    DiscordQueueManager へ enqueue する共通関数。
    拡張側はこれを直接呼ばない。safe_* が内部で使う。

    重要:
      - 実際の RateLimit(429) の sleep/retry は「キュー側(worker)」で行う想定。
      - ここでは「通知に必要なメタ情報」を enqueue に渡す。
    """
    return await discord_queue.enqueue(
        coro_factory,
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,

        # ---- 追加: キュー側での 429 通知/ログ出しに使う ----
        route=route,
        bucket_key=bucket_key,
        on_rate_limit=notifier,
        notify_threshold=notify_threshold,
    )
