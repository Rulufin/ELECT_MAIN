from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from google.cloud.firestore_v1 import AsyncClient
from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue

logger = logging.getLogger(__name__)


class FirestoreBase:
    """全 FS_* クラスの基底クラス。Queue操作を集約する。"""

    def __init__(self, queue_manager=firestore_queue) -> None:
        self.db: AsyncClient = client.firestore_db
        self.queue = queue_manager

    async def _run(self, async_fn) -> Any:
        """任意の async fn をキュー経由で実行する。"""
        try:
            return await self.queue.enqueue(async_fn)
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] queue error: {e}", exc_info=True)
            return None

    async def _fetch(self, doc_ref) -> Any:
        """doc_ref.get() をキュー経由で実行する。"""
        async def _op():
            return await doc_ref.get()
        return await self._run(_op)

    async def _save(self, doc_ref, data: Dict[str, Any], *, merge: bool = True) -> Any:
        """doc_ref.set() をキュー経由で実行する。"""
        async def _op():
            return await doc_ref.set(data, merge=merge)
        return await self._run(_op)

    async def _update(self, doc_ref, data: Dict[str, Any]) -> Any:
        """doc_ref.update() をキュー経由で実行する。"""
        async def _op():
            return await doc_ref.update(data)
        return await self._run(_op)

    async def _delete(self, doc_ref) -> Any:
        """doc_ref.delete() をキュー経由で実行する。"""
        async def _op():
            return await doc_ref.delete()
        return await self._run(_op)

    async def _add(self, col_ref, data: Dict[str, Any]) -> Any:
        """col_ref.add() をキュー経由で実行する。"""
        async def _op():
            return await col_ref.add(data)
        return await self._run(_op)
