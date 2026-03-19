# utils/discord/safe_call.py
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional, TypeVar

import discord

from queuemanagers.discord_queue_core import discord_queue
from .typing import CoroFactory
from .errors import (
    is_rate_limited,
    extract_retry_after,
    is_transient_http_error,
    is_forbidden,
    is_not_found,
    RateLimitInfo,
    DiscordQueueAborted
)
from .logging import log_exception
from .constants import DEFAULT_RETRIES, DEFAULT_RETRY_SLEEP_CAP

T = TypeVar("T")
logger = logging.getLogger(__name__)

RateLimitNotifier = Callable[[RateLimitInfo], Awaitable[None]]


async def safe_call(
    coro_factory: CoroFactory[T],
    *,
    action: str,
    bucket_id: Optional[str] = None,
    serial_id: Optional[str] = None,
    use_queue: bool = False,
    retries: int = DEFAULT_RETRIES,
    retry_sleep_cap: float = DEFAULT_RETRY_SLEEP_CAP,
    swallow_forbidden: bool = True,
    swallow_not_found: bool = True,
    route: str | None = None,
    bucket_key: str | None = None,
    on_rate_limit: Optional[RateLimitNotifier] = None,
    notify_threshold: float = 15.0,
) -> Optional[T]:

    async def _run_direct() -> Optional[T]:
        attempt = 0
        while True:
            attempt += 1
            try:
                return await coro_factory()

            except Exception as e:
                if is_rate_limited(e):
                    retry_after, _is_global = extract_retry_after(e)
                    retry_after = max(0.0, min(float(retry_after), float(retry_sleep_cap)))
                    logger.warning(
                        f"[safe_call] rate limited action={action} sleep={retry_after:.2f}s attempt={attempt}/{retries+1}"
                    )
                    await asyncio.sleep(retry_after)
                    if attempt <= retries + 1:
                        continue

                if is_transient_http_error(e) and attempt <= retries + 1:
                    backoff = min(2.0 ** (attempt - 1), retry_sleep_cap)
                    logger.warning(
                        f"[safe_call] transient error action={action} backoff={backoff:.2f}s attempt={attempt}/{retries+1}"
                    )
                    await asyncio.sleep(backoff)
                    continue

                if swallow_forbidden and is_forbidden(e):
                    log_exception(e, action=action)
                    return None

                if swallow_not_found and is_not_found(e):
                    log_exception(e, action=action)
                    return None

                log_exception(e, action=action)
                raise

    if use_queue:
        if not bucket_id:
            raise ValueError("safe_call(use_queue=True) requires bucket_id (route+major).")

        try:
            res = await discord_queue.enqueue(
                lambda: coro_factory(),
                bucket_id=bucket_id,
                serial_id=serial_id,
                route=route,
                bucket_key=bucket_key,
                on_rate_limit=on_rate_limit,
                notify_threshold=notify_threshold,
            )
            return res

        # ★ここが追加：長いレート制限で「意図的に中断」したケースは握って None
        except DiscordQueueAborted as e:
            logger.warning(
                f"[safe_call] aborted action={action} retry_after={e.retry_after:.2f}s route={e.route}"
            )
            return None

        except Exception as e:
            if swallow_forbidden and is_forbidden(e):
                log_exception(e, action=action)
                return None
            if swallow_not_found and is_not_found(e):
                log_exception(e, action=action)
                return None
            log_exception(e, action=action)
            raise

    return await _run_direct()
