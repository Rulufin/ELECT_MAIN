from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_IO_WORKERS_DEFAULT = 8
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=_IO_WORKERS_DEFAULT,
            thread_name_prefix="io-pool",
        )
    return _executor


async def run(fn: Callable[..., T], *args: Any) -> T:
    """同期ブロッキング I/O をスレッドプールで非同期実行する。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), fn, *args)


def shutdown(wait: bool = True) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=not wait)
        _executor = None
        logger.info("[io_pool] shutdown")
