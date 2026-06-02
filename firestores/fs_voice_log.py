import logging
from typing import Any, Dict, List, Optional, Union, Literal, Tuple

from google.cloud.firestore_v1 import AsyncClient
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
VoiceEventType = Literal["JOIN", "LEAVE", "MUTE_ON", "MUTE_OFF"]

# コレクション名
COL_VC_LOG = "VC_LOG"


class FS_Voice_Log(FirestoreBase):
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
        super().__init__()
        if db is not None:
            self.db = db

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
    # VC doc operations (public thin wrappers)
    # -------------------------
    async def get_vc_doc(self, vc_id: IntStr):
        """VC_LOG/{vc_id} の DocumentSnapshot を返す（無ければ None）"""
        async def runner():
            return await self._get_vc_doc(vc_id)
        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] get_vc_doc queue error: {e}", exc_info=True)
            return None

    async def get_vc_info(self, vc_id: IntStr) -> Dict[str, Any]:
        """VC_LOG/{vc_id} の dict（無ければ {}）"""
        async def runner():
            return await self._get_vc_info(vc_id)
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Voice_Log] get_vc_info queue error: {e}", exc_info=True)
            return {}

    async def ensure_vc_doc(
        self,
        vc_id: IntStr,
        guild_id: IntStr,
        *,
        created_at: Optional[DatetimeWithNanoseconds] = None,
        category_id: Optional[IntStr] = None,
        owner_user_id: Optional[IntStr] = None,
    ) -> None:
        async def runner():
            return await self._ensure_vc_doc(
                vc_id, guild_id,
                created_at=created_at,
                category_id=category_id,
                owner_user_id=owner_user_id,
            )
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] ensure_vc_doc queue error: {e}", exc_info=True)

    async def set_vc_deleted(
        self,
        vc_id: IntStr,
        *,
        deleted_at: DatetimeWithNanoseconds,
    ) -> None:
        async def runner():
            return await self._set_vc_deleted(vc_id, deleted_at=deleted_at)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] set_vc_deleted queue error: {e}", exc_info=True)

    async def set_vc_owner_if_empty(self, vc_id: IntStr, owner_user_id: IntStr) -> None:
        """owner_user_id が未設定ならセットする（既にあれば何もしない）"""
        async def runner():
            return await self._set_vc_owner_if_empty(vc_id, owner_user_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] set_vc_owner_if_empty queue error: {e}", exc_info=True)

    async def mark_points_calculated(
        self,
        vc_id: IntStr,
        *,
        ts: DatetimeWithNanoseconds,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        async def runner():
            return await self._mark_points_calculated(vc_id, ts=ts, meta=meta)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] mark_points_calculated queue error: {e}", exc_info=True)

    async def is_points_calculated(self, vc_id: IntStr) -> bool:
        async def runner():
            return await self._is_points_calculated(vc_id)
        try:
            return await self._run(runner) or False
        except Exception as e:
            logger.error(f"[FS_Voice_Log] is_points_calculated queue error: {e}", exc_info=True)
            return False

    # -------------------------
    # Member / Event operations (public thin wrappers)
    # -------------------------
    async def ensure_member_doc(self, vc_id: IntStr, user_id: IntStr) -> None:
        """members/{user_id} を作る（空docでOK）"""
        async def runner():
            return await self._ensure_member_doc(vc_id, user_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] ensure_member_doc queue error: {e}", exc_info=True)

    async def add_event(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        event_type: VoiceEventType,
        ts: DatetimeWithNanoseconds,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """members/{user_id}/events にイベント追加"""
        async def runner():
            return await self._add_event(vc_id, user_id, event_type=event_type, ts=ts, extra=extra)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] add_event queue error: {e}", exc_info=True)

    async def list_member_ids(self, vc_id: IntStr, *, limit: int = 2000) -> List[str]:
        """members コレクションの user_id(doc id) を取得"""
        async def runner():
            return await self._list_member_ids(vc_id, limit=limit)
        try:
            return await self._run(runner) or []
        except Exception as e:
            logger.error(f"[FS_Voice_Log] list_member_ids queue error: {e}", exc_info=True)
            return []

    async def fetch_events_for_member(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        include_event_doc_id: bool = True,
    ) -> List[Dict[str, Any]]:
        """指定メンバーの events を全部取得（ts昇順）"""
        async def runner():
            return await self._fetch_events_for_member(vc_id, user_id, include_event_doc_id=include_event_doc_id)
        try:
            return await self._run(runner) or []
        except Exception as e:
            logger.error(f"[FS_Voice_Log] fetch_events_for_member queue error: {e}", exc_info=True)
            return []

    async def fetch_events_for_member_paged(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        limit: int = 500,
        start_after_ts: Optional[DatetimeWithNanoseconds] = None,
        include_event_doc_id: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Optional[DatetimeWithNanoseconds]]:
        """events を ts 昇順でページング取得。戻り: (events, next_start_after_ts)"""
        async def runner():
            return await self._fetch_events_for_member_paged(
                vc_id, user_id,
                limit=limit,
                start_after_ts=start_after_ts,
                include_event_doc_id=include_event_doc_id,
            )
        try:
            return await self._run(runner) or ([], None)
        except Exception as e:
            logger.error(f"[FS_Voice_Log] fetch_events_for_member_paged queue error: {e}", exc_info=True)
            return [], None

    # -------------------------
    # Bulk fetch (VC内訳 全取得) (public thin wrapper)
    # -------------------------
    async def fetch_vc_all(
        self,
        vc_id: IntStr,
        *,
        include_event_doc_id: bool = True,
        include_empty_members: bool = True,
    ) -> Dict[str, Any]:
        """VC_LOG/{vc_id} 配下を可能な限り "全部" 取得して返す（集計/バックアップ向け）"""
        async def runner():
            return await self._fetch_vc_all(
                vc_id,
                include_event_doc_id=include_event_doc_id,
                include_empty_members=include_empty_members,
            )
        try:
            return await self._run(runner) or {"vc_id": str(vc_id), "vc": {}, "members": {}}
        except Exception as e:
            logger.error(f"[FS_Voice_Log] fetch_vc_all queue error: {e}", exc_info=True)
            return {"vc_id": str(vc_id), "vc": {}, "members": {}}

    # -------------------------
    # Migration helpers (public thin wrapper)
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
        async def runner():
            return await self._migrate_meta_to_toplevel_one(vc_id, delete_legacy_fields=delete_legacy_fields)
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Voice_Log] migrate_meta_to_toplevel_one queue error: {e}", exc_info=True)
            return {}

    # =========================================================
    # Private実処理メソッド（Firestoreを直接呼ぶ）
    # =========================================================

    # -------------------------
    # VC doc operations (private)
    # -------------------------
    async def _get_vc_doc(self, vc_id: IntStr):
        """VC_LOG/{vc_id} の DocumentSnapshot を返す（無ければ None）"""
        snap = await self._vc_doc(vc_id).get()
        if not snap or not getattr(snap, "exists", False):
            return None
        return snap

    async def _get_vc_info(self, vc_id: IntStr) -> Dict[str, Any]:
        """VC_LOG/{vc_id} の dict（無ければ {}）"""
        snap = await self._get_vc_doc(vc_id)
        return snap.to_dict() if snap else {}

    async def _ensure_vc_doc(
        self,
        vc_id: IntStr,
        guild_id: IntStr,
        *,
        created_at: Optional[DatetimeWithNanoseconds] = None,
        category_id: Optional[IntStr] = None,
        owner_user_id: Optional[IntStr] = None,
    ) -> None:
        doc_ref = self._vc_doc(vc_id)
        snap = await doc_ref.get()

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

            await doc_ref.set(patch, merge=True)
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
            await doc_ref.set(patch, merge=True)

    async def _set_vc_deleted(
        self,
        vc_id: IntStr,
        *,
        deleted_at: DatetimeWithNanoseconds,
    ) -> None:
        await self._vc_doc(vc_id).set({"deleted_at": deleted_at}, merge=True)

    async def _set_vc_owner_if_empty(self, vc_id: IntStr, owner_user_id: IntStr) -> None:
        """owner_user_id が未設定ならセットする（既にあれば何もしない）"""
        doc_ref = self._vc_doc(vc_id)
        snap = await doc_ref.get()
        if snap and getattr(snap, "exists", False):
            d = snap.to_dict() or {}
            if d.get("owner_user_id"):
                return

        await doc_ref.set({"owner_user_id": str(owner_user_id)}, merge=True)

    async def _mark_points_calculated(
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

        await doc_ref.set(data, merge=True)

    async def _is_points_calculated(self, vc_id: IntStr) -> bool:
        info = await self._get_vc_info(vc_id)
        return bool(info.get("points_calculated", False))

    # -------------------------
    # Member / Event operations (private)
    # -------------------------
    async def _ensure_member_doc(self, vc_id: IntStr, user_id: IntStr) -> None:
        """members/{user_id} を作る（空docでOK）"""
        await self._member_doc(vc_id, user_id).set({}, merge=True)

    async def _add_event(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        event_type: VoiceEventType,
        ts: DatetimeWithNanoseconds,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """members/{user_id}/events にイベント追加"""
        # メンバードキュメントを直接作成
        await self._member_doc(vc_id, user_id).set({}, merge=True)

        payload: Dict[str, Any] = {
            "type": event_type,
            "ts": ts,
        }
        if extra:
            # extra のキー衝突は上書き許容
            payload.update(extra)

        await self._events_col(vc_id, user_id).add(payload)

    async def _list_member_ids(self, vc_id: IntStr, *, limit: int = 2000) -> List[str]:
        """members コレクションの user_id(doc id) を取得"""
        out: List[str] = []
        async for ms in self._members_col(vc_id).limit(limit).stream():
            out.append(ms.id)
        return out

    async def _fetch_events_for_member(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        include_event_doc_id: bool = True,
    ) -> List[Dict[str, Any]]:
        """指定メンバーの events を全部取得（ts昇順）"""
        out: List[Dict[str, Any]] = []
        q = self._events_col(vc_id, user_id).order_by("ts")
        async for ev_snap in q.stream():
            d = ev_snap.to_dict() or {}
            if include_event_doc_id:
                d["_id"] = ev_snap.id
            out.append(d)
        return out

    async def _fetch_events_for_member_paged(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        limit: int = 500,
        start_after_ts: Optional[DatetimeWithNanoseconds] = None,
        include_event_doc_id: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Optional[DatetimeWithNanoseconds]]:
        """events を ts 昇順でページング取得。戻り: (events, next_start_after_ts)"""
        out: List[Dict[str, Any]] = []
        last_ts: Optional[DatetimeWithNanoseconds] = None

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

        return out, last_ts

    # -------------------------
    # Bulk fetch (VC内訳 全取得) (private)
    # -------------------------
    async def _fetch_vc_all(
        self,
        vc_id: IntStr,
        *,
        include_event_doc_id: bool = True,
        include_empty_members: bool = True,
    ) -> Dict[str, Any]:
        """VC_LOG/{vc_id} 配下を可能な限り "全部" 取得して返す（集計/バックアップ向け）"""
        snap = await self._vc_doc(vc_id).get()
        if not snap or not getattr(snap, "exists", False):
            return {"vc_id": str(vc_id), "vc": {}, "members": {}}

        vc_data = snap.to_dict() or {}

        members_out: Dict[str, Any] = {}
        members_col = self._members_col(vc_id)

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

        return {
            "vc_id": str(vc_id),
            "vc": vc_data,
            "members": members_out,
        }

    # -------------------------
    # Migration helpers (private)
    # -------------------------
    async def _migrate_meta_to_toplevel_one(self, vc_id: IntStr, *, delete_legacy_fields: bool = False) -> Dict[str, Any]:
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
        snap = await doc_ref.get()
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
            await doc_ref.set(patch, merge=True)

        if delete_legacy_fields:
            # Firestoreの削除 sentinel
            from google.cloud.firestore_v1 import DELETE_FIELD

            del_patch: Dict[str, Any] = {"meta": DELETE_FIELD}
            for k in list(data.keys()):
                if isinstance(k, str) and k.startswith("meta."):
                    del_patch[k] = DELETE_FIELD

            await doc_ref.set(del_patch, merge=True)

        return {"status": "OK", "vc_id": str(vc_id), "patched_keys": sorted(list(patch.keys()))}
