# firestores/fs_talk_history.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, Tuple

from google.cloud.firestore_v1 import AsyncClient, Increment, SERVER_TIMESTAMP  # type: ignore

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase

logger = logging.getLogger(__name__)

IntStr = Union[int, str]

# -------------------------
# Collection names
# -------------------------
COL_TALK_HISTORY_PAIRS = "TalkHistory_Pairs"
COL_TALK_HISTORY_TARGET_INDEX = "TalkHistory_TargetIndex"


@dataclass(frozen=True)
class TalkHistoryDoc:
    user1_id: int
    user2_id: int
    shared_seconds: float
    qualified: bool
    last_talked_at: float
    updated_at: float

    @property
    def pair_key(self) -> str:
        return f"{self.user1_id}_{self.user2_id}"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TalkHistoryDoc":
        def _to_ts(v: Any) -> float:
            if v is None:
                return 0.0
            if hasattr(v, "timestamp"):
                try:
                    return float(v.timestamp())
                except Exception:
                    return 0.0
            try:
                return float(v)
            except Exception:
                return 0.0

        return cls(
            user1_id=int(d.get("user1_id", 0) or 0),
            user2_id=int(d.get("user2_id", 0) or 0),
            shared_seconds=float(d.get("shared_seconds", 0.0) or 0.0),
            qualified=bool(d.get("qualified", False)),
            last_talked_at=_to_ts(d.get("last_talked_at")),
            updated_at=_to_ts(d.get("updated_at")),
        )


class FS_Talk_History(FirestoreBase):
    """
    Firestore:

      TalkHistory_Pairs/{min_user_id}_{max_user_id}
        user1_id: int
        user2_id: int
        shared_seconds: float
        qualified: bool
        last_talked_at: timestamp | None
        updated_at: timestamp

      TalkHistory_TargetIndex/{target_user_id}
        target_user_id: int
        eligible_voter_ids: { "<voter_id>": True, ... }
        updated_at: timestamp

    設計:
      - 正本は TalkHistory_Pairs
      - 投票判定や一覧表示を軽くするため TalkHistory_TargetIndex を補助的に持つ
      - qualified=True になった時に index を更新する
      - 固定ギルド前提のため guild_id は持たない
    """

    def __init__(
        self,
        db: Optional[AsyncClient] = None,
        *,
        qualify_seconds: float = 300.0,
    ):
        super().__init__()
        if db is not None:
            self.db = db
        self.qualify_seconds = float(qualify_seconds)

    # -------------------------
    # Path helpers
    # -------------------------
    def _pairs_col(self):
        return self.db.collection(COL_TALK_HISTORY_PAIRS)

    def _pair_doc(self, user1_id: IntStr, user2_id: IntStr):
        a, b = self.normalize_pair(user1_id, user2_id)
        return self._pairs_col().document(f"{a}_{b}")

    def _target_index_col(self):
        return self.db.collection(COL_TALK_HISTORY_TARGET_INDEX)

    def _target_index_doc(self, target_user_id: IntStr):
        return self._target_index_col().document(str(int(target_user_id)))

    # -------------------------
    # Normalize helpers
    # -------------------------
    @staticmethod
    def normalize_pair(user1_id: IntStr, user2_id: IntStr) -> Tuple[int, int]:
        a = int(user1_id)
        b = int(user2_id)
        if a == b:
            raise ValueError("user1_id and user2_id must be different")
        return (a, b) if a < b else (b, a)

    @classmethod
    def build_pair_key(cls, user1_id: IntStr, user2_id: IntStr) -> str:
        a, b = cls.normalize_pair(user1_id, user2_id)
        return f"{a}_{b}"

    # -------------------------
    # Read helpers (private、Firestore直接呼び出し)
    # -------------------------
    async def _get_pair_dict(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> Optional[Dict[str, Any]]:
        ref = self._pair_doc(user1_id, user2_id)
        snap = await ref.get()
        if not snap or not getattr(snap, "exists", False):
            return None
        return snap.to_dict() or {}

    async def _get_target_index_dict(
        self,
        target_user_id: IntStr,
    ) -> Optional[Dict[str, Any]]:
        ref = self._target_index_doc(target_user_id)
        snap = await ref.get()
        if not snap or not getattr(snap, "exists", False):
            return None
        return snap.to_dict() or {}

    # -------------------------
    # Pair read (public thin wrapper)
    # -------------------------
    async def get_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> Optional[TalkHistoryDoc]:
        async def runner():
            return await self._get_pair(user1_id, user2_id)
        try:
            return await self._run(runner) or None
        except Exception as e:
            logger.error(f"[FS_Talk_History] get_pair queue error: {e}", exc_info=True)
            return None

    async def _get_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> Optional[TalkHistoryDoc]:
        d = await self._get_pair_dict(user1_id, user2_id)
        if d is None:
            return None
        return TalkHistoryDoc.from_dict(d)

    async def get_pair_info(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> Dict[str, Any]:
        async def runner():
            return await self._get_pair_info(user1_id, user2_id)
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Talk_History] get_pair_info queue error: {e}", exc_info=True)
            return {}

    async def _get_pair_info(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> Dict[str, Any]:
        d = await self._get_pair_dict(user1_id, user2_id)
        return d or {}

    async def has_talked(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> bool:
        async def runner():
            return await self._has_talked(user1_id, user2_id)
        try:
            return await self._run(runner) or False
        except Exception as e:
            logger.error(f"[FS_Talk_History] has_talked queue error: {e}", exc_info=True)
            return False

    async def _has_talked(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> bool:
        d = await self._get_pair_dict(user1_id, user2_id)
        if d is None:
            return False
        return bool(d.get("qualified", False))

    async def get_shared_seconds(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> float:
        async def runner():
            return await self._get_shared_seconds(user1_id, user2_id)
        try:
            return await self._run(runner) or 0.0
        except Exception as e:
            logger.error(f"[FS_Talk_History] get_shared_seconds queue error: {e}", exc_info=True)
            return 0.0

    async def _get_shared_seconds(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> float:
        d = await self._get_pair_dict(user1_id, user2_id)
        if d is None:
            return 0.0
        return float(d.get("shared_seconds", 0.0) or 0.0)

    # -------------------------
    # Target index read (public thin wrapper)
    # -------------------------
    async def get_target_index(
        self,
        target_user_id: IntStr,
    ) -> Dict[str, Any]:
        async def runner():
            return await self._get_target_index(target_user_id)
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Talk_History] get_target_index queue error: {e}", exc_info=True)
            return {}

    async def _get_target_index(
        self,
        target_user_id: IntStr,
    ) -> Dict[str, Any]:
        d = await self._get_target_index_dict(target_user_id)
        return d or {}

    async def get_eligible_voter_ids(
        self,
        target_user_id: IntStr,
    ) -> List[int]:
        async def runner():
            return await self._get_eligible_voter_ids(target_user_id)
        try:
            return await self._run(runner) or []
        except Exception as e:
            logger.error(f"[FS_Talk_History] get_eligible_voter_ids queue error: {e}", exc_info=True)
            return []

    async def _get_eligible_voter_ids(
        self,
        target_user_id: IntStr,
    ) -> List[int]:
        d = await self._get_target_index_dict(target_user_id)
        if d is None:
            return []
        raw = d.get("eligible_voter_ids", {}) or {}
        if not isinstance(raw, dict):
            return []

        out: List[int] = []
        for k, v in raw.items():
            if not v:
                continue
            try:
                out.append(int(k))
            except Exception:
                continue
        return sorted(set(out))

    async def is_eligible_voter_for_target(
        self,
        voter_user_id: IntStr,
        target_user_id: IntStr,
    ) -> bool:
        async def runner():
            return await self._is_eligible_voter_for_target(voter_user_id, target_user_id)
        try:
            return await self._run(runner) or False
        except Exception as e:
            logger.error(f"[FS_Talk_History] is_eligible_voter_for_target queue error: {e}", exc_info=True)
            return False

    async def _is_eligible_voter_for_target(
        self,
        voter_user_id: IntStr,
        target_user_id: IntStr,
    ) -> bool:
        if int(voter_user_id) == int(target_user_id):
            return False

        d = await self._get_target_index_dict(target_user_id)
        if d is None:
            return False
        raw = d.get("eligible_voter_ids", {}) or {}
        if not isinstance(raw, dict):
            return False

        return bool(raw.get(str(int(voter_user_id)), False))

    # -------------------------
    # Ensure docs (public thin wrapper)
    # -------------------------
    async def ensure_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> None:
        async def runner():
            return await self._ensure_pair(user1_id, user2_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] ensure_pair queue error: {e}", exc_info=True)

    async def _ensure_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> None:
        a, b = self.normalize_pair(user1_id, user2_id)
        ref = self._pair_doc(a, b)

        payload = {
            "user1_id": int(a),
            "user2_id": int(b),
            "shared_seconds": 0.0,
            "qualified": False,
            "last_talked_at": None,
            "updated_at": SERVER_TIMESTAMP,
        }
        await ref.set(payload, merge=True)

    async def ensure_target_index(
        self,
        target_user_id: IntStr,
    ) -> None:
        async def runner():
            return await self._ensure_target_index(target_user_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] ensure_target_index queue error: {e}", exc_info=True)

    async def _ensure_target_index(
        self,
        target_user_id: IntStr,
    ) -> None:
        ref = self._target_index_doc(target_user_id)
        payload = {
            "target_user_id": int(target_user_id),
            "eligible_voter_ids": {},
            "updated_at": SERVER_TIMESTAMP,
        }
        await ref.set(payload, merge=True)

    # -------------------------
    # Pair write (public thin wrapper)
    # -------------------------
    async def add_shared_seconds(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        seconds: float,
        *,
        auto_qualify: bool = True,
        qualify_seconds: Optional[float] = None,
        update_index: bool = True,
    ) -> float:
        """
        shared_seconds を加算し、加算後の total を返す。

        注意:
          - total 判定のため一度 read してから write している
          - 厳密な同時更新競合までケアするなら transaction 化余地あり
          - 現段階では queue ベースのシンプル実装
        """
        async def runner():
            return await self._add_shared_seconds(
                user1_id, user2_id, seconds,
                auto_qualify=auto_qualify,
                qualify_seconds=qualify_seconds,
                update_index=update_index,
            )
        try:
            return await self._run(runner) or 0.0
        except Exception as e:
            logger.error(f"[FS_Talk_History] add_shared_seconds queue error: {e}", exc_info=True)
            return 0.0

    async def _add_shared_seconds(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        seconds: float,
        *,
        auto_qualify: bool = True,
        qualify_seconds: Optional[float] = None,
        update_index: bool = True,
    ) -> float:
        add_sec = float(seconds)
        if add_sec <= 0:
            d = await self._get_pair_dict(user1_id, user2_id)
            return float(d.get("shared_seconds", 0.0) or 0.0) if d else 0.0

        threshold = float(
            self.qualify_seconds if qualify_seconds is None else qualify_seconds
        )

        a, b = self.normalize_pair(user1_id, user2_id)
        d = await self._get_pair_dict(a, b)
        current = float(d.get("shared_seconds", 0.0) or 0.0) if d else 0.0
        total = current + add_sec
        became_qualified = bool(auto_qualify and total >= threshold)

        ref = self._pair_doc(a, b)
        payload: Dict[str, Any] = {
            "user1_id": int(a),
            "user2_id": int(b),
            "shared_seconds": Increment(add_sec),
            "last_talked_at": SERVER_TIMESTAMP,
            "updated_at": SERVER_TIMESTAMP,
        }
        if became_qualified:
            payload["qualified"] = True

        await ref.set(payload, merge=True)

        if became_qualified and update_index:
            await self._add_pair_to_both_target_indexes(
                user1_id=a,
                user2_id=b,
            )

        return total

    async def set_shared_seconds(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        shared_seconds: float,
        *,
        auto_qualify: bool = True,
        qualify_seconds: Optional[float] = None,
        update_index: bool = True,
    ) -> None:
        async def runner():
            return await self._set_shared_seconds(
                user1_id, user2_id, shared_seconds,
                auto_qualify=auto_qualify,
                qualify_seconds=qualify_seconds,
                update_index=update_index,
            )
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] set_shared_seconds queue error: {e}", exc_info=True)

    async def _set_shared_seconds(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        shared_seconds: float,
        *,
        auto_qualify: bool = True,
        qualify_seconds: Optional[float] = None,
        update_index: bool = True,
    ) -> None:
        total = max(0.0, float(shared_seconds))
        threshold = float(
            self.qualify_seconds if qualify_seconds is None else qualify_seconds
        )
        qualified = bool(auto_qualify and total >= threshold)

        a, b = self.normalize_pair(user1_id, user2_id)
        ref = self._pair_doc(a, b)

        payload: Dict[str, Any] = {
            "user1_id": int(a),
            "user2_id": int(b),
            "shared_seconds": float(total),
            "updated_at": SERVER_TIMESTAMP,
        }
        if auto_qualify:
            payload["qualified"] = qualified
            if qualified:
                payload["last_talked_at"] = SERVER_TIMESTAMP

        await ref.set(payload, merge=True)

        if update_index:
            if qualified:
                await self._add_pair_to_both_target_indexes(
                    user1_id=a,
                    user2_id=b,
                )
            else:
                await self._remove_pair_from_both_target_indexes(
                    user1_id=a,
                    user2_id=b,
                )

    async def mark_qualified(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        qualified: bool = True,
        *,
        update_index: bool = True,
    ) -> None:
        async def runner():
            return await self._mark_qualified(
                user1_id, user2_id, qualified,
                update_index=update_index,
            )
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] mark_qualified queue error: {e}", exc_info=True)

    async def _mark_qualified(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        qualified: bool = True,
        *,
        update_index: bool = True,
    ) -> None:
        a, b = self.normalize_pair(user1_id, user2_id)
        ref = self._pair_doc(a, b)

        payload: Dict[str, Any] = {
            "user1_id": int(a),
            "user2_id": int(b),
            "qualified": bool(qualified),
            "updated_at": SERVER_TIMESTAMP,
        }
        if qualified:
            payload["last_talked_at"] = SERVER_TIMESTAMP

        await ref.set(payload, merge=True)

        if update_index:
            if qualified:
                await self._add_pair_to_both_target_indexes(
                    user1_id=a,
                    user2_id=b,
                )
            else:
                await self._remove_pair_from_both_target_indexes(
                    user1_id=a,
                    user2_id=b,
                )

    async def touch_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> None:
        async def runner():
            return await self._touch_pair(user1_id, user2_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] touch_pair queue error: {e}", exc_info=True)

    async def _touch_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> None:
        a, b = self.normalize_pair(user1_id, user2_id)
        ref = self._pair_doc(a, b)
        payload = {
            "user1_id": int(a),
            "user2_id": int(b),
            "last_talked_at": SERVER_TIMESTAMP,
            "updated_at": SERVER_TIMESTAMP,
        }
        await ref.set(payload, merge=True)

    async def delete_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        *,
        remove_index: bool = False,
    ) -> None:
        async def runner():
            return await self._delete_pair(user1_id, user2_id, remove_index=remove_index)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] delete_pair queue error: {e}", exc_info=True)

    async def _delete_pair(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
        *,
        remove_index: bool = False,
    ) -> None:
        a, b = self.normalize_pair(user1_id, user2_id)

        if remove_index:
            await self._remove_pair_from_both_target_indexes(
                user1_id=a,
                user2_id=b,
            )

        await self._pair_doc(a, b).delete()

    # -------------------------
    # Target index write (public thin wrapper)
    # -------------------------
    async def add_eligible_voter_to_target(
        self,
        target_user_id: IntStr,
        voter_user_id: IntStr,
    ) -> None:
        """
        TalkHistory_TargetIndex/{target_user_id}.eligible_voter_ids["voter_id"] = True
        """
        async def runner():
            return await self._add_eligible_voter_to_target(target_user_id, voter_user_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] add_eligible_voter_to_target queue error: {e}", exc_info=True)

    async def _add_eligible_voter_to_target(
        self,
        target_user_id: IntStr,
        voter_user_id: IntStr,
    ) -> None:
        if int(target_user_id) == int(voter_user_id):
            return

        ref = self._target_index_doc(target_user_id)
        payload = {
            "target_user_id": int(target_user_id),
            f"eligible_voter_ids.{int(voter_user_id)}": True,
            "updated_at": SERVER_TIMESTAMP,
        }
        await ref.set(payload, merge=True)

    async def remove_eligible_voter_from_target(
        self,
        target_user_id: IntStr,
        voter_user_id: IntStr,
    ) -> None:
        """
        dict map なので delete sentinel で消す
        """
        async def runner():
            return await self._remove_eligible_voter_from_target(target_user_id, voter_user_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Talk_History] remove_eligible_voter_from_target queue error: {e}", exc_info=True)

    async def _remove_eligible_voter_from_target(
        self,
        target_user_id: IntStr,
        voter_user_id: IntStr,
    ) -> None:
        from google.cloud.firestore_v1 import DELETE_FIELD  # type: ignore

        ref = self._target_index_doc(target_user_id)
        payload = {
            f"eligible_voter_ids.{int(voter_user_id)}": DELETE_FIELD,
            "updated_at": SERVER_TIMESTAMP,
        }
        await ref.set(payload, merge=True)

    async def rebuild_target_index_for_user(
        self,
        target_user_id: IntStr,
        *,
        limit: int = 5000,
    ) -> Dict[str, Any]:
        """
        Pairs から target_user_id に関する qualified=True のものを総なめして
        TalkHistory_TargetIndex/{target_user_id} を再構築する。

        件数が非常に多い場合は後でページング検討。
        """
        async def runner():
            return await self._rebuild_target_index_for_user(target_user_id, limit=limit)
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Talk_History] rebuild_target_index_for_user queue error: {e}", exc_info=True)
            return {}

    async def _rebuild_target_index_for_user(
        self,
        target_user_id: IntStr,
        *,
        limit: int = 5000,
    ) -> Dict[str, Any]:
        target_id = int(target_user_id)
        eligible_map: Dict[str, bool] = {}

        try:
            async for snap in self._pairs_col().limit(limit).stream():
                d = snap.to_dict() or {}
                if not d.get("qualified", False):
                    continue

                u1 = int(d.get("user1_id", 0) or 0)
                u2 = int(d.get("user2_id", 0) or 0)

                if u1 == target_id and u2 > 0:
                    eligible_map[str(u2)] = True
                elif u2 == target_id and u1 > 0:
                    eligible_map[str(u1)] = True

        except Exception as e:
            logger.exception(
                f"[FS_Talk_History] _rebuild_target_index_for_user failed "
                f"target_user_id={target_user_id} err={e}"
            )
            return {
                "status": "ERROR",
                "target_user_id": str(target_user_id),
                "eligible_count": 0,
            }

        ref = self._target_index_doc(target_id)
        payload = {
            "target_user_id": int(target_id),
            "eligible_voter_ids": eligible_map,
            "updated_at": SERVER_TIMESTAMP,
        }
        await ref.set(payload, merge=True)

        return {
            "status": "OK",
            "target_user_id": str(target_id),
            "eligible_count": len(eligible_map),
        }

    # -------------------------
    # Pair -> Target index sync helpers (private、直接呼び出し)
    # -------------------------
    async def _add_pair_to_both_target_indexes(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> None:
        """
        user1 <-> user2 が qualified になったので、
        双方向に target index を張る
        """
        a, b = self.normalize_pair(user1_id, user2_id)

        await self._add_eligible_voter_to_target(
            target_user_id=a,
            voter_user_id=b,
        )
        await self._add_eligible_voter_to_target(
            target_user_id=b,
            voter_user_id=a,
        )

    async def _remove_pair_from_both_target_indexes(
        self,
        user1_id: IntStr,
        user2_id: IntStr,
    ) -> None:
        a, b = self.normalize_pair(user1_id, user2_id)

        await self._remove_eligible_voter_from_target(
            target_user_id=a,
            voter_user_id=b,
        )
        await self._remove_eligible_voter_from_target(
            target_user_id=b,
            voter_user_id=a,
        )

    # -------------------------
    # Bulk / list helpers (public thin wrapper)
    # -------------------------
    async def list_pairs_for_user(
        self,
        user_id: IntStr,
        *,
        qualified_only: bool = False,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """
        user_id を含む pair を全走査で返す。
        Firestore の複合検索に寄せるより、まずはシンプル運用向け。
        """
        async def runner():
            return await self._list_pairs_for_user(user_id, qualified_only=qualified_only, limit=limit)
        try:
            return await self._run(runner) or []
        except Exception as e:
            logger.error(f"[FS_Talk_History] list_pairs_for_user queue error: {e}", exc_info=True)
            return []

    async def _list_pairs_for_user(
        self,
        user_id: IntStr,
        *,
        qualified_only: bool = False,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        uid = int(user_id)
        out: List[Dict[str, Any]] = []

        try:
            async for snap in self._pairs_col().limit(limit).stream():
                d = snap.to_dict() or {}
                u1 = int(d.get("user1_id", 0) or 0)
                u2 = int(d.get("user2_id", 0) or 0)

                if uid not in (u1, u2):
                    continue
                if qualified_only and not bool(d.get("qualified", False)):
                    continue

                d["_id"] = snap.id
                out.append(d)

        except Exception as e:
            logger.exception(
                f"[FS_Talk_History] _list_pairs_for_user failed "
                f"user_id={user_id} err={e}"
            )

        return out

    async def fetch_all(
        self,
        *,
        include_target_indexes: bool = True,
        limit_pairs: int = 10000,
        limit_indexes: int = 10000,
    ) -> Dict[str, Any]:
        """
        TalkHistory 全体を可能な限り全部返す
        """
        async def runner():
            return await self._fetch_all(
                include_target_indexes=include_target_indexes,
                limit_pairs=limit_pairs,
                limit_indexes=limit_indexes,
            )
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Talk_History] fetch_all queue error: {e}", exc_info=True)
            return {}

    async def _fetch_all(
        self,
        *,
        include_target_indexes: bool = True,
        limit_pairs: int = 10000,
        limit_indexes: int = 10000,
    ) -> Dict[str, Any]:
        pairs: Dict[str, Any] = {}
        target_indexes: Dict[str, Any] = {}

        try:
            async for snap in self._pairs_col().limit(limit_pairs).stream():
                pairs[snap.id] = snap.to_dict() or {}
        except Exception as e:
            logger.exception(
                f"[FS_Talk_History] _fetch_all pairs failed err={e}"
            )

        if include_target_indexes:
            try:
                async for snap in self._target_index_col().limit(limit_indexes).stream():
                    target_indexes[snap.id] = snap.to_dict() or {}
            except Exception as e:
                logger.exception(
                    f"[FS_Talk_History] _fetch_all target_indexes failed err={e}"
                )

        return {
            "pairs": pairs,
            "target_indexes": target_indexes,
        }

    # -------------------------
    # Convenience (public thin wrapper)
    # -------------------------
    async def can_vote_for(
        self,
        voter_id: IntStr,
        target_id: IntStr,
        *,
        prefer_index: bool = True,
    ) -> bool:
        """
        投票可否の最低条件:
          - 自分自身には投票できない
          - talked / qualified 済み

        prefer_index=True:
          まず TargetIndex を見て、無ければ Pair を見る
        """
        async def runner():
            return await self._can_vote_for(voter_id, target_id, prefer_index=prefer_index)
        try:
            return await self._run(runner) or False
        except Exception as e:
            logger.error(f"[FS_Talk_History] can_vote_for queue error: {e}", exc_info=True)
            return False

    async def _can_vote_for(
        self,
        voter_id: IntStr,
        target_id: IntStr,
        *,
        prefer_index: bool = True,
    ) -> bool:
        if int(voter_id) == int(target_id):
            return False

        if prefer_index:
            ok = await self._is_eligible_voter_for_target(
                voter_user_id=voter_id,
                target_user_id=target_id,
            )
            if ok:
                return True

        return await self._has_talked(
            user1_id=voter_id,
            user2_id=target_id,
        )
