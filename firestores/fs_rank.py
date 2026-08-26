from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Union

from google.cloud.firestore_v1 import AsyncClient, Increment

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase

logger = logging.getLogger(__name__)

IntStr = Union[int, str]

COLLECTION = "Rank"


@dataclass(frozen=True)
class RankState:
    user_id: int
    total_tc: int
    total_vc: int


class FS_Rank(FirestoreBase):
    """
    Rank/{user_id}
      total_tc : int  (テキストチャンネル累計ランクポイント)
      total_vc : int  (ボイスチャンネル累計ランクポイント)
    """

    def __init__(self, queue_manager=firestore_queue) -> None:
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient.")
        super().__init__(queue_manager)

    def _doc(self, user_id: IntStr):
        return self.db.collection(COLLECTION).document(str(user_id))

    # ─────────────────────────────────────────────
    # Read
    # ─────────────────────────────────────────────

    async def get_state(self, user_id: IntStr) -> Optional[RankState]:
        snap = await self._fetch(self._doc(user_id))
        if snap is None or not snap.exists:
            return None
        d = snap.to_dict() or {}
        return RankState(
            user_id=int(user_id),
            total_tc=int(d.get("total_tc", 0) or 0),
            total_vc=int(d.get("total_vc", 0) or 0),
        )

    # ─────────────────────────────────────────────
    # Write (atomic increment)
    # ─────────────────────────────────────────────

    async def add_tc_points(self, user_id: IntStr, add: int) -> None:
        if add == 0:
            return
        await self._update(self._doc(user_id), {"total_tc": Increment(int(add))})

    async def add_vc_points(self, user_id: IntStr, add: int) -> None:
        if add == 0:
            return
        await self._update(self._doc(user_id), {"total_vc": Increment(int(add))})

    async def set_points(
        self,
        user_id: IntStr,
        *,
        total_tc: Optional[int] = None,
        total_vc: Optional[int] = None,
    ) -> None:
        """指定フィールドを絶対値で上書きする（管理者用）。省略したフィールドは変更しない。"""
        fields: dict = {}
        if total_tc is not None:
            fields["total_tc"] = int(total_tc)
        if total_vc is not None:
            fields["total_vc"] = int(total_vc)
        if not fields:
            return
        await self._save(self._doc(user_id), fields, merge=True)

    async def ensure_exists(self, user_id: IntStr) -> None:
        """ドキュメントが存在しない場合のみ初期化する。"""
        await self._save(
            self._doc(user_id),
            {"total_tc": 0, "total_vc": 0},
            merge=True,
        )
