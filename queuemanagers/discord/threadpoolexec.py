# threadpoolexec.py
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

# 運用に合わせて調整
_IO_WORKERS_DEFAULT = 8

_executor: ThreadPoolExecutor | None = None

def start(max_workers: int = _IO_WORKERS_DEFAULT) -> None:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="io-pool")

def started() -> bool:
    return _executor is not None

async def run_blocking_io(fn: Callable[..., Any], *args) -> Any:
    """同期I/O関数をスレッドで非同期化して実行。"""
    if _executor is None:
        start()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn, *args)

def shutdown(wait: bool = True) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=not wait)
        _executor = None
