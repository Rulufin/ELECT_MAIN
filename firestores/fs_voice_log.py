import logging
from typing import Any, Dict, List, Optional, Union, Literal, Tuple

from google.cloud.firestore_v1 import AsyncClient
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
VoiceEventType = Literal["JOIN", "LEAVE", "MUTE_ON", "MUTE_OFF"]

# コレクション名
COL_VC_LOG = "VC_LOG"


class FS_Voice_Log:
    """
    Firestore: VC_LOG

    新仕様（トップレベル統一）:
      VC_LOG/{vc_id}
        created_at: timestamp
        guild_id: str
        vc_id: str
        deleted_at: timestamp
        owner_user_id: str
        points_calculated: bool
        points_calculated_at: timestamp

        members (subcollection)
          {user_id} (doc)  ※空でもOK
            events (subcollection)
              {event_id} (doc)
                type: "JOIN" | "LEAVE" | "MUTE_ON" | "MUTE_OFF"
                ts: timestamp
                ...extra
    """

    def __init__(self, db: Optional[AsyncClient] = None):
        self.db: AsyncClient = db or client.firestore_db
        self.queue = firestore_queue

    # -------------------------
    # Path helpers
    # -------------------------
    def _vc_doc(self, vc_id: IntStr):
        return self.db.collection(COL_VC_LOG).document(str(vc_id))

    def _members_col(self, vc_id: IntStr):
        return self._vc_doc(vc_id).collection("members")

    def _member_doc(self, vc_id: IntStr, user_id: IntStr):
        return self._members_col(vc_id).document(str(user_id))

    def _events_col(self, vc_id: IntStr, user_id: IntStr):
        return self._member_doc(vc_id, user_id).collection("events")

    # -------------------------
    # Queue wrappers (get / set / add / delete)
    # -------------------------
    async def _q_get(self, doc_ref):
        async def _op():
            return await doc_ref.get()

        try:
            return await self.queue.enqueue(_op)
        except Exception as e:
            logger.exception(f"[FS_Voice_Log] _q_get failed: {doc_ref.path} err={e}")
            return None

    async def _q_set(self, doc_ref, data: Dict[str, Any], *, merge: bool = True):
        async def _op():
            return await doc_ref.set(data, merge=merge)

        try:
            return await self.queue.enqueue(_op)
        except Exception as e:
            logger.exception(f"[FS_Voice_Log] _q_set failed: {doc_ref.path} data={data} err={e}")
            return None

    async def _q_update(self, doc_ref, data: Dict[str, Any]):
        async def _op():
            return await doc_ref.update(data)

        try:
            return await self.queue.enqueue(_op)
        except Exception as e:
            # update は doc が無いと失敗するので注意
            logger.exception(f"[FS_Voice_Log] _q_update failed: {doc_ref.path} data={data} err={e}")
            return None

    async def _q_add(self, col_ref, data: Dict[str, Any]):
        async def _op():
            return await col_ref.add(data)

        try:
            return await self.queue.enqueue(_op)
        except Exception as e:
            logger.exception(f"[FS_Voice_Log] _q_add failed: {getattr(col_ref, 'path', col_ref)} data={data} err={e}")
            return None

    async def _q_delete(self, doc_ref):
        async def _op():
            return await doc_ref.delete()

        try:
            return await self.queue.enqueue(_op)
        except Exception as e:
            logger.exception(f"[FS_Voice_Log] _q_delete failed: {doc_ref.path} err={e}")
            return None

    # -------------------------
    # VC doc operations
    # -------------------------
    async def get_vc_doc(self, vc_id: IntStr):
        """VC_LOG/{vc_id} の DocumentSnapshot を返す（無ければ None）"""
        snap = await self._q_get(self._vc_doc(vc_id))
        if not snap or not getattr(snap, "exists", False):
            return None
        return snap

    async def get_vc_info(self, vc_id: IntStr) -> Dict[str, Any]:
        """VC_LOG/{vc_id} の dict（無ければ {}）"""
        snap = await self.get_vc_doc(vc_id)
        return snap.to_dict() if snap else {}

    async def ensure_vc_doc(
        self,
        vc_id: IntStr,
        guild_id: IntStr,
        *,
        created_at: Optional[DatetimeWithNanoseconds] = None,
        category_id: Optional[IntStr] = None,
        owner_user_id: Optional[IntStr] = None,
    ) -> None:
        doc_ref = self._vc_doc(vc_id)
        snap = await self._q_get(doc_ref)

        patch: Dict[str, Any] = {}

        if not snap or not getattr(snap, "exists", False):
            patch["guild_id"] = str(guild_id)
            patch["vc_id"] = str(vc_id)
            if created_at is not None:
                patch["created_at"] = created_at
            if category_id is not None:
                patch["category_id"] = int(category_id)
            if owner_user_id is not None:
                patch["owner_user_id"] = str(owner_user_id)

            await self._q_set(doc_ref, patch, merge=True)
            return

        d = snap.to_dict() or {}

        if "guild_id" not in d:
            patch["guild_id"] = str(guild_id)
        if "vc_id" not in d:
            patch["vc_id"] = str(vc_id)
        if created_at is not None and not d.get("created_at"):
            patch["created_at"] = created_at
        if category_id is not None and d.get("category_id") is None:
            patch["category_id"] = int(category_id)
        if owner_user_id is not None and not d.get("owner_user_id"):
            patch["owner_user_id"] = str(owner_user_id)

        if patch:
            await self._q_set(doc_ref, patch, merge=True)

    async def set_vc_deleted(
        self,
        vc_id: IntStr,
        *,
        deleted_at: DatetimeWithNanoseconds,
    ) -> None:
        await self._q_set(self._vc_doc(vc_id), {"deleted_at": deleted_at}, merge=True)

    async def set_vc_owner_if_empty(self, vc_id: IntStr, owner_user_id: IntStr) -> None:
        """
        owner_user_id が未設定ならセットする（既にあれば何もしない）
        """
        doc_ref = self._vc_doc(vc_id)
        snap = await self._q_get(doc_ref)
        if snap and getattr(snap, "exists", False):
            d = snap.to_dict() or {}
            if d.get("owner_user_id"):
                return

        await self._q_set(doc_ref, {"owner_user_id": str(owner_user_id)}, merge=True)

    async def mark_points_calculated(
        self,
        vc_id: IntStr,
        *,
        ts: DatetimeWithNanoseconds,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        doc_ref = self._vc_doc(vc_id)

        data = {
            "points_calculated": True,
            "points_calculated_at": ts,
        }

        if meta:
            data["points_calculated_meta"] = dict(meta)

        await self._q_set(doc_ref, data, merge=True)

    async def is_points_calculated(self, vc_id: IntStr) -> bool:
        info = await self.get_vc_info(vc_id)
        return bool(info.get("points_calculated", False))

    # -------------------------
    # Member / Event operations
    # -------------------------
    async def ensure_member_doc(self, vc_id: IntStr, user_id: IntStr) -> None:
        """
        members/{user_id} を作る（空docでOK）
        """
        await self._q_set(self._member_doc(vc_id, user_id), {}, merge=True)

    async def add_event(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        event_type: VoiceEventType,
        ts: DatetimeWithNanoseconds,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        members/{user_id}/events にイベント追加
        """
        await self.ensure_member_doc(vc_id, user_id)

        payload: Dict[str, Any] = {
            "type": event_type,
            "ts": ts,
        }
        if extra:
            # extra のキー衝突は上書き許容
            payload.update(extra)

        await self._q_add(self._events_col(vc_id, user_id), payload)

    async def list_member_ids(self, vc_id: IntStr, *, limit: int = 2000) -> List[str]:
        """
        members コレクションの user_id(doc id) を取得
        """
        out: List[str] = []
        try:
            async for ms in self._members_col(vc_id).limit(limit).stream():
                out.append(ms.id)
        except Exception as e:
            logger.exception(f"[FS_Voice_Log] list_member_ids failed vc_id={vc_id} err={e}")
        return out

    async def fetch_events_for_member(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        include_event_doc_id: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        指定メンバーの events を全部取得（ts昇順）
        """
        out: List[Dict[str, Any]] = []
        try:
            q = self._events_col(vc_id, user_id).order_by("ts")
            async for ev_snap in q.stream():
                d = ev_snap.to_dict() or {}
                if include_event_doc_id:
                    d["_id"] = ev_snap.id
                out.append(d)
        except Exception as e:
            logger.exception(f"[FS_Voice_Log] fetch_events_for_member failed vc={vc_id} user={user_id} err={e}")
        return out

    async def fetch_events_for_member_paged(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        limit: int = 500,
        start_after_ts: Optional[DatetimeWithNanoseconds] = None,
        include_event_doc_id: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Optional[DatetimeWithNanoseconds]]:
        """
        events を ts 昇順でページング取得
        戻り: (events, next_start_after_ts)
        """
        out: List[Dict[str, Any]] = []
        last_ts: Optional[DatetimeWithNanoseconds] = None

        try:
            q = self._events_col(vc_id, user_id).order_by("ts").limit(limit)
            if start_after_ts is not None:
                q = q.start_after({"ts": start_after_ts})

            async for ev_snap in q.stream():
                d = ev_snap.to_dict() or {}
                if include_event_doc_id:
                    d["_id"] = ev_snap.id
                out.append(d)
                # ts は必須前提（無い場合は next が壊れるので注意）
                last_ts = d.get("ts")

        except Exception as e:
            logger.exception(f"[FS_Voice_Log] fetch_events_for_member_paged failed vc={vc_id} user={user_id} err={e}")
            return [], None

        return out, last_ts

    # -------------------------
    # Bulk fetch (VC内訳 全取得)
    # -------------------------
    async def fetch_vc_all(
        self,
        vc_id: IntStr,
        *,
        include_event_doc_id: bool = True,
        include_empty_members: bool = True,
    ) -> Dict[str, Any]:
        """
        VC_LOG/{vc_id} 配下を可能な限り “全部” 取得して返す（集計/バックアップ向け）
        """
        vc_snap = await self.get_vc_doc(vc_id)
        if not vc_snap:
            return {"vc_id": str(vc_id), "vc": {}, "members": {}}

        vc_data = vc_snap.to_dict() or {}

        members_out: Dict[str, Any] = {}
        members_col = self._members_col(vc_id)

        try:
            async for member_snap in members_col.stream():
                user_id = member_snap.id
                member_doc_data = member_snap.to_dict() or {}

                events_list: List[Dict[str, Any]] = []
                events_q = self._events_col(vc_id, user_id).order_by("ts")
                async for ev_snap in events_q.stream():
                    ev = ev_snap.to_dict() or {}
                    if include_event_doc_id:
                        ev["_id"] = ev_snap.id
                    events_list.append(ev)

                if (not include_empty_members) and (not member_doc_data) and (not events_list):
                    continue

                members_out[user_id] = {
                    "member_doc": member_doc_data,
                    "events": events_list,
                }

        except Exception as e:
            logger.exception(f"[FS_Voice_Log] fetch_vc_all failed vc_id={vc_id} err={e}")

        return {
            "vc_id": str(vc_id),
            "vc": vc_data,
            "members": members_out,
        }

    # -------------------------
    # Migration helpers (旧 meta 構造 → 新トップレベル)
    # -------------------------
    async def migrate_meta_to_toplevel_one(self, vc_id: IntStr, *, delete_legacy_fields: bool = False) -> Dict[str, Any]:
        """
        旧:
          meta(map) + "meta.xxx"(ドットキー) が混在している可能性がある
        新:
          全部トップレベルへ正規化

        - meta(map) の中身はトップレベルへコピー
        - "meta.xxx" は xxx としてトップレベルへコピー
        - delete_legacy_fields=True の場合は meta と meta.xxx を削除（※危険なので通常はFalse推奨）
        """
        doc_ref = self._vc_doc(vc_id)
        snap = await self._q_get(doc_ref)
        if not snap or not getattr(snap, "exists", False):
            return {"status": "NOT_FOUND", "vc_id": str(vc_id)}

        data = snap.to_dict() or {}

        patch: Dict[str, Any] = {}

        # 1) meta(map) → top-level
        legacy_meta = data.get("meta")
        if isinstance(legacy_meta, dict):
            for k, v in legacy_meta.items():
                # 既に top-level にある場合は上書きしない（安全優先）
                if k not in data:
                    patch[k] = v

        # 2) "meta.xxx" → xxx
        for k, v in data.items():
            if isinstance(k, str) and k.startswith("meta."):
                sub = k.split(".", 1)[1]
                if sub and (sub not in data):
                    patch[sub] = v

        if patch:
            await self._q_set(doc_ref, patch, merge=True)

        if delete_legacy_fields:
            # Firestoreの削除 sentinel
            from google.cloud.firestore_v1 import DELETE_FIELD

            del_patch: Dict[str, Any] = {"meta": DELETE_FIELD}
            for k in list(data.keys()):
                if isinstance(k, str) and k.startswith("meta."):
                    del_patch[k] = DELETE_FIELD

            await self._q_set(doc_ref, del_patch, merge=True)

        return {"status": "OK", "vc_id": str(vc_id), "patched_keys": sorted(list(patch.keys()))}
