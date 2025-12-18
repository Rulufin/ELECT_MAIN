# queuemanagers/discord/dc_queuemanager.py
import asyncio
import logging
import random
from functools import partial
from typing import Any, Callable, Optional, Tuple, Dict, List

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Rate limit helpers
# ─────────────────────────────────────────────────────────

class RateLimitInfo:
    """Per-bucket rate limit info（粗い制御用）."""
    def __init__(self) -> None:
        self.limit: Optional[int] = None
        self.remaining: Optional[int] = None
        # Reset-After（秒）ではなく、loop.time() 基準の絶対時刻に正規化して保持
        self.reset_at: Optional[float] = None
        # レガシー互換のために残すが、新実装では未使用でもOK
        self.reset_after: Optional[float] = None
        self.lock = asyncio.Lock()


class GlobalRateLimit:
    """Discord の Global 429 を表現する軽いロック."""
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._reset_at: Optional[float] = None

    async def wait_if_global_limited(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            if self._reset_at and self._reset_at > now:
                wait_time = self._reset_at - now
                logger.info(f"[RL] Global rate limit active: sleeping {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                self._reset_at = None

    async def set_global_limit(self, retry_after: float) -> None:
        async with self._lock:
            self._reset_at = asyncio.get_event_loop().time() + float(retry_after)


# ─────────────────────────────────────────────────────────
# Queue Manager
# ─────────────────────────────────────────────────────────

class QueueManager_Discord:
    """
    Discord向けHTTP実行のための非同期キュー。
    - normal / fastlane の二系統（別セマフォ）
    - 短時間429は内部sleep→自動再投入（ジッター付き）
    - 長時間429は呼び出し側へ返却（上位で再スケジュール）
    - Global 429 に対応
    - HTTP層から渡される X-RateLimit-* ヘッダを per-bucket に反映
    """

    def __init__(self, concurrency: int = 5, fastlane_concurrency: int = 2) -> None:
        # キュー（func, args, future, bucket_id, is_http_task）
        self.queue: asyncio.Queue[Tuple[Callable[..., Any], tuple, asyncio.Future, Optional[str], bool]] = asyncio.Queue()
        self.fastlane: asyncio.Queue[Tuple[Callable[..., Any], tuple, asyncio.Future, Optional[str], bool]] = asyncio.Queue()

        self.concurrency = max(1, int(concurrency))
        self.fastlane_concurrency = max(1, int(fastlane_concurrency))

        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.fastlane_semaphore = asyncio.Semaphore(self.fastlane_concurrency)

        self.workers: List[asyncio.Task] = []
        self.fastlane_workers: List[asyncio.Task] = []

        self.running = False
        self.worker_task_lock = asyncio.Lock()

        self.rate_limits: Dict[str, RateLimitInfo] = {}
        self.global_limit = GlobalRateLimit()

        # 短時間429を内部リトライするしきい値（秒）
        self.short_wait_threshold: float = 30.0

    # ───────────────────────────
    # lifecycle
    # ───────────────────────────

    async def start_workers(self) -> None:
        async with self.worker_task_lock:
            if self.running:
                return
            self.running = True
            logger.info("[Queue] Starting workers...")
            self.workers = [
                asyncio.create_task(self._worker_task(False), name=f"discord-http-normal-{i}")
                for i in range(self.concurrency)
            ]
            self.fastlane_workers = [
                asyncio.create_task(self._worker_task(True), name=f"discord-http-fastlane-{i}")
                for i in range(self.fastlane_concurrency)
            ]

    async def stop_workers(self) -> None:
        async with self.worker_task_lock:
            if not self.running:
                return
            self.running = False
            logger.info("[Queue] Stopping workers...")
            for t in self.workers + self.fastlane_workers:
                t.cancel()
            await asyncio.gather(*self.workers, *self.fastlane_workers, return_exceptions=True)
            self.workers.clear()
            self.fastlane_workers.clear()
            logger.info("[Queue] Workers stopped.")

    async def drain_and_stop(self, timeout: float = 5.0) -> None:
        """
        穏やかに停止: キューが空になるのを待ってから stop。
        timeout 超過時はキャンセル。
        """
        try:
            await asyncio.wait_for(self.queue.join(), timeout=timeout)
            await asyncio.wait_for(self.fastlane.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("[Queue] drain timeout; cancelling workers.")
        finally:
            await self.stop_workers()

    # ───────────────────────────
    # bucket helpers
    # ───────────────────────────

    def get_or_create_bucket(self, bucket_id: str) -> RateLimitInfo:
        if bucket_id not in self.rate_limits:
            self.rate_limits[bucket_id] = RateLimitInfo()
        return self.rate_limits[bucket_id]

    async def handle_response_headers(self, headers: dict, bucket_info: RateLimitInfo) -> None:
        """
        HTTP層から渡されたレスポンスヘッダを反映する。
        - X-RateLimit-Limit / Remaining / Reset-After を使用
        - Reset-After(秒) は loop.time() による絶対時刻 reset_at に変換
        """
        try:
            if 'X-RateLimit-Limit' in headers:
                bucket_info.limit = int(float(headers['X-RateLimit-Limit']))
            if 'X-RateLimit-Remaining' in headers:
                bucket_info.remaining = int(float(headers['X-RateLimit-Remaining']))
            if 'X-RateLimit-Reset-After' in headers:
                reset_after_s = float(headers['X-RateLimit-Reset-After'])
                bucket_info.reset_at = asyncio.get_event_loop().time() + reset_after_s
                # 互換（使わない前提）
                bucket_info.reset_after = reset_after_s
        except Exception:
            # 値がない/数値変換失敗は無視
            pass

    # ───────────────────────────
    # enqueue
    # ───────────────────────────

    async def enqueue(
        self,
        func: Callable[..., Any],
        *args,
        bucket_id: Optional[str] = None,
        is_http_task: bool = True,
        priority: str = "normal",
    ):
        """
        タスクを投入して結果(Future)をawaitで返す。
        - is_http_task=True の場合は bucket_id が必須（RL管理のため）
        - priority in {"normal", "fastlane"}
        """
        if is_http_task and bucket_id is None:
            func_name = func.func.__name__ if isinstance(func, partial) else getattr(func, "__name__", str(func))
            logger.error(f"[Queue] HTTP tasks require bucket_id (func={func_name}, args={args}). Skipped.")
            return "bucket_id is None"

        fut: asyncio.Future = asyncio.Future()
        q = self.fastlane if priority == "fastlane" else self.queue
        await q.put((func, args, fut, bucket_id, is_http_task))

        if not self.running:
            await self.start_workers()

        return await fut

    async def enqueue_fastlane(
        self,
        func: Callable[..., Any],
        *args,
        bucket_id: Optional[str] = None,
        is_http_task: bool = True,
    ):
        """ACK/defer 用のショートカット。"""
        return await self.enqueue(func, *args, bucket_id=bucket_id, is_http_task=is_http_task, priority="fastlane")

    # ───────────────────────────
    # 429 handler
    # ───────────────────────────

    async def handle_429(self, rate_limit_data: dict) -> Optional[float]:
        """
        ResponseHandler が返す rate_limit データを処理。
        - retry_after < short_wait_threshold: 内部でsleep→再投入（呼び出し元からはNoneを返す）
        - それ以外: 呼び出し側に retry_after を返す（長時間は上位で再スケジュール）
        """
        retry_after = float(rate_limit_data.get("retry_after", 1.0))
        is_global = bool(rate_limit_data.get("global", False))

        if retry_after < self.short_wait_threshold:
            # 短時間は内部リトライ。再衝突を避けるため小さなジッターを加える
            jitter = random.uniform(0.05, 0.15)
            if is_global:
                # 短時間でも global のときはロックを張ると体感が安定
                await self.global_limit.set_global_limit(retry_after + jitter)
            logger.info(f"[RL] Short 429: sleeping {retry_after:.2f}s + jitter {jitter:.2f}s then retry")
            await asyncio.sleep(retry_after + jitter)
            return None

        # 長時間は上位へ返す
        if is_global:
            await self.global_limit.set_global_limit(retry_after)
            logger.info(f"[RL] Global 429: retry after {retry_after:.2f}s")
        else:
            logger.info(f"[RL] Local 429: retry after {retry_after:.2f}s")
        return retry_after

    # ───────────────────────────
    # worker
    # ───────────────────────────

    async def _worker_task(self, fastlane: bool) -> None:
        """
        fastlane=True  : ACKなど最優先処理。独立したセマフォで実行。
        fastlane=False : 通常処理。
        """
        q = self.fastlane if fastlane else self.queue
        sem = self.fastlane_semaphore if fastlane else self.semaphore
        lane = "FAST" if fastlane else "NORM"

        try:
            while self.running:
                try:
                    func, args, fut, bucket_id, is_http_task = await q.get()

                    # グローバルRL待機
                    await self.global_limit.wait_if_global_limited()

                    # バケット先読み待機（remaining==0 の場合は reset_at まで寝る）
                    if bucket_id:
                        bucket_info = self.get_or_create_bucket(bucket_id)
                        async with bucket_info.lock:
                            if bucket_info.remaining is not None and bucket_info.remaining <= 0:
                                now = asyncio.get_event_loop().time()
                                if bucket_info.reset_at and bucket_info.reset_at > now:
                                    sleep_for = bucket_info.reset_at - now
                                else:
                                    sleep_for = 1.0  # フォールバック
                                logger.info(f"[RL][{lane}] bucket={bucket_id} sleeping {sleep_for:.2f}s (remaining<=0)")
                                await asyncio.sleep(sleep_for)

                    async with sem:
                        try:
                            # 実行（HTTP層は dict を返す前提）
                            result = await func(*args)

                            if is_http_task:
                                status = result.get("status")

                                if status == "rate_limit":
                                    # 短時間なら内部sleep→同レーンへ再投入
                                    retry_after = await self.handle_429(result)
                                    if retry_after is None:
                                        await q.put((func, args, fut, bucket_id, is_http_task))
                                        continue
                                    else:
                                        # 長時間は結果を返す（上位で再スケジュール）
                                        if not fut.done():
                                            fut.set_result({
                                                "status": "rate_limit",
                                                "retry_after": retry_after,
                                                "data": None,
                                                "status_code": 429
                                            })
                                        continue

                                if status == "error":
                                    if not fut.done():
                                        fut.set_exception(Exception(f"HTTP error: {result.get('data')}"))
                                else:
                                    if not fut.done():
                                        fut.set_result(result)
                            else:
                                # 非HTTPタスクは素通し
                                if not fut.done():
                                    fut.set_result(result)

                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            logger.exception(f"[Queue][{lane}] Task execution failed")
                            if not fut.done():
                                fut.set_exception(Exception("Task execution failed"))

                except asyncio.CancelledError:
                    logger.info(f"[Queue][{lane}] Worker cancelled.")
                    break
                except Exception:
                    logger.exception(f"[Queue][{lane}] Unexpected error in worker.")
                finally:
                    q.task_done()

        finally:
            logger.info(f"[Queue][{lane}] Worker finished.")


# ─────────────────────────────────────────────────────────
# シングルトン（インポート側はこれを使えばOK）
# ─────────────────────────────────────────────────────────
discord_queue = QueueManager_Discord()
