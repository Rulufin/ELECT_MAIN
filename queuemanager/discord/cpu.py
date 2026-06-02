from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_CPU_WORKERS_DEFAULT = 2
_executor: ProcessPoolExecutor | None = None


def _get_executor() -> ProcessPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=_CPU_WORKERS_DEFAULT)
        logger.info(f"[cpu_pool] started workers={_CPU_WORKERS_DEFAULT}")
    return _executor


async def run(fn: Callable[..., T], *args: Any) -> T:
    """
    CPU バウンドな処理（画像生成・重い計算など）を別プロセスで非同期実行する。

    制約: fn と args は pickle 可能である必要がある。
    ラムダ・クロージャは使えないため、モジュールトップレベルの関数を渡すこと。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), fn, *args)


def shutdown(wait: bool = True) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=not wait)
        _executor = None
        logger.info("[cpu_pool] shutdown")
