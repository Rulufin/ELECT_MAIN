# queuemanager/discord_queue.py
from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

import discord

from utils.discord.safe_calls.errors import (
    # 既存
    is_rate_limited,
    extract_retry_after,
    is_transient_http_error,
    # 追加想定（RateLimitInfo を errors に置く/または re-export する）
    RateLimitInfo,
    DiscordQueueAborted,
)

T = TypeVar("T")
CoroFactory = Callable[[], Awaitable[T]]
RateLimitNotifier = Callable[[RateLimitInfo], Awaitable[None]]

logger = logging.getLogger(__name__)


@dataclass
class _Gate:
    """A simple time-gate guarded by a lock (used for global and bucket waits)."""
    lock: asyncio.Lock
    reset_at: float = 0.0  # monotonic time

    async def wait_if_active(self) -> None:
        async with self.lock:
            now = time.monotonic()
            if self.reset_at > now:
                wait_time = self.reset_at - now
                logger.info(f"[discord_queue] Gate active, sleeping {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                # clear after wait
                self.reset_at = 0.0

    async def set(self, retry_after: float) -> None:
        async with self.lock:
            until = time.monotonic() + max(0.0, float(retry_after))
            # keep the longer one if overlapping
            if until > self.reset_at:
                self.reset_at = until


@dataclass
class _BucketState:
    lock: asyncio.Lock
    gate: _Gate


@dataclass
class _QueueItem:
    coro_factory: CoroFactory[T]
    fut: asyncio.Future
    bucket_id: str
    serial_id: Optional[str]
    # ---- for rate limit UX / tracing ----
    route: Optional[str]
    bucket_key: Optional[str]
    on_rate_limit: Optional[RateLimitNotifier]
    notify_threshold: float

class DiscordQueueManager:
    """
    Discord 작업 실행 큐.
    - Global rate limit gate
    - Per-bucket gate (route+major 기반 bucket_id)
    - Optional serial lock (e.g. user:123 / message:456) for app-level ordering

    追加:
    - 429 の retry_after が長いとき、on_rate_limit による通知（タスク中1回だけ）
    """

    def __init__(self, concurrency: int = 10, queue_maxsize: int = 1000) -> None:
        # (priority, seq, _QueueItem) — seq で同優先度内の FIFO を保証
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=queue_maxsize)
        self._counter = itertools.count()
        self._concurrency = max(1, int(concurrency))
        self._sem = asyncio.Semaphore(self._concurrency)
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._lifecycle_lock = asyncio.Lock()

        self._global_gate = _Gate(lock=asyncio.Lock())

        # bucket_id -> _BucketState
        self._buckets: dict[str, _BucketState] = {}

        # serial_id -> asyncio.Lock
        self._serial_locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._running:
                return
            self._running = True
            self._workers = [asyncio.create_task(self._worker(i)) for i in range(self._concurrency)]
            logger.info(f"[discord_queue] started workers={self._concurrency}")

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if not self._running:
                return
            self._running = False
            for w in self._workers:
                w.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
            logger.info("[discord_queue] stopped")

    def _get_bucket(self, bucket_id: str) -> _BucketState:
        st = self._buckets.get(bucket_id)
        if st is None:
            st = _BucketState(lock=asyncio.Lock(), gate=_Gate(lock=asyncio.Lock()))
            self._buckets[bucket_id] = st
        return st

    def _get_serial_lock(self, serial_id: str) -> asyncio.Lock:
        lk = self._serial_locks.get(serial_id)
        if lk is None:
            lk = asyncio.Lock()
            self._serial_locks[serial_id] = lk
        return lk

    async def enqueue(
        self,
        coro_factory: CoroFactory[T],
        *,
        bucket_id: str,
        serial_id: Optional[str] = None,
        priority: int = 1,
        # ---- rate limit通知用メタ ----
        route: str | None = None,
        bucket_key: str | None = None,
        on_rate_limit: Optional[RateLimitNotifier] = None,
        notify_threshold: float = 15.0,
    ) -> T:
        """
        Enqueue a coroutine factory.
        - priority: 0 = 優先（Interaction followup/edit）, 1 = 通常（default）
        - bucket_id: required. Use route+major key.
        - serial_id: optional. Extra ordering key (user/message/etc).
        """
        if not self._running:
            await self.start()

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        item = _QueueItem(
            coro_factory=coro_factory,
            fut=fut,
            bucket_id=bucket_id,
            serial_id=serial_id,
            route=route,
            bucket_key=bucket_key,
            on_rate_limit=on_rate_limit,
            notify_threshold=float(notify_threshold),
        )
        seq = next(self._counter)
        await self._queue.put((priority, seq, item))
        return await fut  # type: ignore[return-value]

    async def _worker(self, idx: int) -> None:
        logger.info(f"[discord_queue] worker#{idx} started")
        while self._running:
            item: Optional[_QueueItem] = None
            try:
                _priority, _seq, item = await self._queue.get()

                # 1) global gate
                await self._global_gate.wait_if_active()

                # 2) bucket gate
                bucket = self._get_bucket(item.bucket_id)
                await bucket.gate.wait_if_active()

                # 3) optional serial lock — sem の外で取得してスロットを消費しない
                serial_lock: Optional[asyncio.Lock] = None
                if item.serial_id:
                    serial_lock = self._get_serial_lock(item.serial_id)

                if serial_lock:
                    async with serial_lock:
                        await self._execute_with_retries(item)
                else:
                    await self._execute_with_retries(item)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[discord_queue] worker unexpected error")
                # _execute_with_retries に到達する前に例外した場合 Future を確実に解決する
                if item is not None and not item.fut.done():
                    item.fut.set_exception(
                        RuntimeError("[discord_queue] worker crashed before execution")
                    )
            finally:
                if item is not None:
                    self._queue.task_done()

        logger.info(f"[discord_queue] worker#{idx} finished")

    async def _execute_with_retries(
        self,
        item: _QueueItem,
        *,
        max_retries: int = 3,
    ) -> None:
        """
        セマフォは API 呼び出し時のみ保持。
        sleep はセマフォの外で行いスロットを無駄に占有しない。
        """
        attempt = 0
        notified = False
        sleep_time: float = 0.0

        while True:
            attempt += 1

            # 前回の retry/transient sleep — セマフォの外で待つ
            if sleep_time > 0.0:
                await asyncio.sleep(sleep_time)
                sleep_time = 0.0

            async with self._sem:  # API 呼び出し時だけスロット取得
                try:
                    result = await item.coro_factory()
                    if not item.fut.done():
                        item.fut.set_result(result)
                    return

                except Exception as e:
                    if is_rate_limited(e):
                        retry_after, is_global = extract_retry_after(e)
                        retry_after = max(0.0, float(retry_after))

                        long_wait = retry_after >= float(item.notify_threshold)

                        if is_global:
                            await self._global_gate.set(retry_after)
                            logger.warning(f"[discord_queue] global rate limited. retry_after={retry_after:.2f}s")
                        else:
                            bucket = self._get_bucket(item.bucket_id)
                            await bucket.gate.set(retry_after)
                            logger.warning(
                                f"[discord_queue] bucket rate limited. bucket_id={item.bucket_id} retry_after={retry_after:.2f}s"
                            )

                        if long_wait:
                            if item.on_rate_limit is not None and not notified:
                                notified = True
                                try:
                                    info = RateLimitInfo(
                                        retry_after=retry_after,
                                        is_global=bool(is_global),
                                        route=item.route or f"bucket:{item.bucket_id}",
                                        bucket_key=item.bucket_key,
                                    )
                                    await item.on_rate_limit(info)
                                except Exception:
                                    logger.exception("[discord_queue] on_rate_limit notifier failed")

                            if not item.fut.done():
                                item.fut.set_exception(
                                    DiscordQueueAborted(
                                        "Aborted due to long rate limit; user should retry later.",
                                        retry_after=retry_after,
                                        route=item.route,
                                    )
                                )
                            return

                        if attempt <= max_retries:
                            sleep_time = retry_after  # sem 解放後に sleep
                            continue

                    elif is_transient_http_error(e) and attempt <= max_retries:
                        backoff = min(2.0 ** (attempt - 1), 8.0)
                        logger.warning(
                            f"[discord_queue] transient error, retrying in {backoff:.2f}s "
                            f"attempt={attempt}/{max_retries} err={type(e).__name__}"
                        )
                        sleep_time = backoff  # sem 解放後に sleep
                        continue

                    if not item.fut.done():
                        item.fut.set_exception(e)
                    return
            # async with self._sem を抜けた時点でスロット解放 → 次ループ先頭で sleep


# global singleton like your current style
discord_queue = DiscordQueueManager(concurrency=5)
