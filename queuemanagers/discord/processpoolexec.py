# processpoolexec.py
import asyncio
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable

_CPU_WORKERS_DEFAULT = 2

_executor: ProcessPoolExecutor | None = None

def start(max_workers: int = _CPU_WORKERS_DEFAULT) -> None:
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=max_workers)

def started() -> bool:
    return _executor is not None

async def run_cpu(fn: Callable[..., Any], *args) -> Any:
    """CPUヘビーな純計算関数を別プロセスで実行。"""
    if _executor is None:
        start()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, fn, *args)

def shutdown(wait: bool = True) -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=not wait)
        _executor = None
