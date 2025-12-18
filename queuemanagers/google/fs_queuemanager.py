import asyncio
import logging
import random
import aiohttp
from functools import partial
from google.api_core.exceptions import GoogleAPICallError, RetryError, ResourceExhausted

logger = logging.getLogger(__name__)

class GlobalBackoff:
    """ResourceExhausted発生時に指数バックオフで待機時間を管理するクラス。"""
    def __init__(self, base_backoff=1.0, max_backoff=60.0):
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.current_backoff = 0.0
        self.lock = asyncio.Lock()

    async def wait_if_backoff(self):
        async with self.lock:
            if self.current_backoff > 0:
                wait_time = self.current_backoff
                logger.info(f"Rate limit backoff active. Waiting {wait_time:.2f} seconds...")
                await asyncio.sleep(wait_time)
                # 待機後、ここではまだbackoffをリセットしない。成功時にリセットする。

    async def increase_backoff(self):
        async with self.lock:
            if self.current_backoff == 0.0:
                self.current_backoff = self.base_backoff
            else:
                self.current_backoff = min(self.current_backoff * 2, self.max_backoff)

    async def reset_backoff(self):
        async with self.lock:
            if self.current_backoff != 0.0:
                logger.info("Resetting backoff to 0.0 due to successful request.")
            self.current_backoff = 0.0

class Retry:
    @staticmethod
    async def retry(func, retries=3, delay=2):
        for attempt in range(retries):
            try:
                return await func()
            except (aiohttp.ClientResponseError, GoogleAPICallError, RetryError) as e:
                logger.error(f"Attempt {attempt + 1}/{retries} failed: {type(e).__name__}, {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"General Exception occurred: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(delay)
        raise Exception(f"Failed after {retries} attempts.")

class QueueManager_FireStore:
    def __init__(self, concurrency: int = 5, base_backoff=1.0, max_backoff=60.0):
        self.queue = asyncio.Queue()
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        self.workers = []
        self.running = False
        self.worker_task_lock = asyncio.Lock()
        self.global_backoff = GlobalBackoff(base_backoff=base_backoff, max_backoff=max_backoff)

    async def start_workers(self):
        async with self.worker_task_lock:
            if not self.running:
                self.running = True
                logger.info("Starting workers...")
                for _ in range(self.concurrency):
                    worker = asyncio.create_task(self.worker_task())
                    self.workers.append(worker)

    async def stop_workers(self):
        async with self.worker_task_lock:
            if self.running and self.queue.empty():
                self.running = False
                logger.info("Stopping workers...")
                for worker in self.workers:
                    worker.cancel()
                await asyncio.gather(*self.workers, return_exceptions=True)
                self.workers = []

    async def enqueue(self, func, *args):
        """
        Firestore操作の非同期タスクをキューに投入する。
        - 受け取った関数（func）と引数（args）をキューに投入。
        - タスクが完了するまでawaitする。
        """
        future = asyncio.Future()
        # 関数の名前でタスクタイプを判定
        if func.__name__.startswith('get') or func.__name__.startswith('query'):
            # 読み取りタスクの場合、読み取り専用キューに投入
            await self.queue.put((func, args, future, 'read'))
        else:
            # 書き込みタスクの場合、書き込み専用キューに投入
            await self.queue.put((func, args, future, 'write'))

        if not self.running:
            await self.start_workers()

        return await future

    async def worker_task(self):
        while self.running:
            try:
                func, args, future, task_type = await self.queue.get()

                # グローバルバックオフ中なら待機
                await self.global_backoff.wait_if_backoff()

                async with self.semaphore:
                    try:
                        # 同期関数はスレッドで実行、非同期ならそのまま
                        if not asyncio.iscoroutinefunction(func):
                            wrapped_func = lambda: asyncio.to_thread(partial(func, *args))
                        else:
                            wrapped_func = lambda: func(*args)

                        try:
                            result = await Retry.retry(wrapped_func)
                            # 成功したらバックオフリセット
                            await self.global_backoff.reset_backoff()
                            future.set_result(result)
                        except ResourceExhausted as e:
                            # レートリミット超過時：指数バックオフを増加
                            logger.warning("Rate limit hit (ResourceExhausted). Increasing backoff...")
                            await self.global_backoff.increase_backoff()

                            # バックオフ時間待機
                            await self.global_backoff.wait_if_backoff()

                            # 再度リトライ
                            result = await Retry.retry(wrapped_func)
                            # 成功したらバックオフリセット
                            await self.global_backoff.reset_backoff()
                            future.set_result(result)

                    except Exception as e:
                        logger.error(f"Queue task failed for {getattr(func, '__name__', str(func))} with args {args}", exc_info=True)
                        future.set_exception(e)
                    finally:
                        self.queue.task_done()

            except asyncio.CancelledError:
                break

        await self.stop_workers()

firestore_queue = QueueManager_FireStore(concurrency=5)