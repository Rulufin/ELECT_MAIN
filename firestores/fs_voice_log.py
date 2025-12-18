import logging
from typing import Any, Dict, List, Optional, Union, Literal

from google.cloud.firestore_v1 import AsyncClient
from google.cloud import firestore_v1 as firestore  # noqa: F401  # 将来の拡張用に残しておく
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
VoiceEventType = Literal["JOIN", "LEAVE", "MUTE_ON", "MUTE_OFF"]


class FS_Voice_Log:
    """
    VC_LOG コレクションの Firestore I/O を扱うクラス。

    構造:
    (default)
    ┗ VC_LOG
       ┗ {vc_id}
          ┣ meta (Map)
          ┗ members (SubCollection)
             ┗ {user_id}
                ┗ events (SubCollection)
                   ┗ {event_id}
    """

    ROOT_COLLECTION = "VC_LOG"

    def __init__(
        self,
        root_collection: str = "VC_LOG",
        queue_manager=firestore_queue,  # QueueManager_FireStore を想定
    ):
        # Firestoreクライアント
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")
        self.db: AsyncClient = client.firestore_db
        self.root = root_collection

        # Firestoreキュー
        self.queue = queue_manager

    # ------------- Internal Helpers -------------

    def _vc_doc(self, vc_id: IntStr):
        return self.db.collection(self.root).document(str(vc_id))

    def _member_doc(self, vc_id: IntStr, user_id: IntStr):
        return self._vc_doc(vc_id).collection("members").document(str(user_id))

    def _events_col(self, vc_id: IntStr, user_id: IntStr):
        return self._member_doc(vc_id, user_id).collection("events")

    # --- Queue wrappers (get / set / add / delete) ---

    async def _q_get(self, doc_ref):
        async def get_doc():
            return await doc_ref.get()

        try:
            return await self.queue.enqueue(get_doc)
        except Exception as e:
            logger.error(f"Error in FS_Voice_Log._q_get: {e}")
            return None

    async def _q_set(self, doc_ref, data: Dict[str, Any], merge: bool = True):
        async def set_doc():
            return await doc_ref.set(data, merge=merge)

        try:
            return await self.queue.enqueue(set_doc)
        except Exception as e:
            logger.error(f"Error in FS_Voice_Log._q_set: {e}")
            return None

    async def _q_add(self, col_ref, data: Dict[str, Any]):
        async def add_doc():
            return await col_ref.add(data)

        try:
            return await self.queue.enqueue(add_doc)
        except Exception as e:
            logger.error(f"Error in FS_Voice_Log._q_add: {e}")
            return None

    async def _q_delete(self, doc_ref):
        async def delete_doc():
            return await doc_ref.delete()

        try:
            return await self.queue.enqueue(delete_doc)
        except Exception as e:
            logger.error(f"Error in FS_Voice_Log._q_delete: {e}")
            return None

    # ------------- meta 操作 -------------

    async def get_vc_doc(self, vc_id: IntStr):
        """
        VC_LOG/{vc_id} の DocumentSnapshot を返す。
        存在しない場合は None。
        """
        snap = await self._q_get(self._vc_doc(vc_id))
        if not snap or not snap.exists:
            return None
        return snap

    async def get_vc_meta(self, vc_id: IntStr) -> Dict[str, Any]:
        """
        VC_LOG/{vc_id}.meta を dict で返す。無ければ {}。
        """
        snap = await self.get_vc_doc(vc_id)
        if not snap:
            return {}
        data = snap.to_dict() or {}
        return dict(data.get("meta", {}) or {})

    async def ensure_vc_doc(
        self,
        vc_id: IntStr,
        guild_id: IntStr,
        created_at: Optional[DatetimeWithNanoseconds] = None,
    ) -> None:
        """
        VC_LOG/{vc_id} が無ければ作成。
        既にある場合は created_at は上書きしない。
        """
        doc_ref = self._vc_doc(vc_id)
        snap = await self._q_get(doc_ref)
        if snap and snap.exists:
            return

        meta: Dict[str, Any] = {
            "guild_id": str(guild_id),
            "vc_id": str(vc_id),
        }
        if created_at is not None:
            meta["created_at"] = created_at

        # 新規作成時だけ meta 全体を書き込む
        await self._q_set(doc_ref, {"meta": meta}, merge=True)

    async def set_vc_deleted(
        self,
        vc_id: IntStr,
        deleted_at: DatetimeWithNanoseconds,
    ) -> None:
        """
        VC が削除されたタイミングで meta.deleted_at を設定。
        既存の meta は維持する。
        """
        doc_ref = self._vc_doc(vc_id)
        await self._q_set(
            doc_ref,
            {"meta.deleted_at": deleted_at},
            merge=True,
        )

    async def set_vc_owner_if_empty(self, vc_id: IntStr, user_id: IntStr) -> None:
        """
        meta.owner_user_id が未設定のときだけ、部屋主として user_id をセット。
        既存の meta は維持する。
        """
        doc_ref = self._vc_doc(vc_id)
        snap = await self._q_get(doc_ref)
        if snap and snap.exists:
            meta = (snap.to_dict() or {}).get("meta", {})
            if meta.get("owner_user_id"):
                # 既に設定されているなら何もしない
                return

        await self._q_set(
            doc_ref,
            {"meta.owner_user_id": str(user_id)},
            merge=True,
        )

    async def mark_points_calculated(
        self,
        vc_id: IntStr,
        ts: DatetimeWithNanoseconds,
    ) -> None:
        """
        この VC についてポイント計算済みであることを記録。
        既存の meta は維持する。
        """
        doc_ref = self._vc_doc(vc_id)
        await self._q_set(
            doc_ref,
            {
                "meta.points_calculated": True,
                "meta.points_calculated_at": ts,
            },
            merge=True,
        )

    async def is_points_calculated(self, vc_id: IntStr) -> bool:
        """
        この VC のポイント計算が完了済みかどうか。
        """
        snap = await self.get_vc_doc(vc_id)
        if not snap:
            return False
        meta = (snap.to_dict() or {}).get("meta", {})
        return bool(meta.get("points_calculated", False))

    # ------------- イベント追加 -------------

    async def add_event(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        *,
        event_type: VoiceEventType,
        ts: DatetimeWithNanoseconds,
        from_channel_id: Optional[IntStr] = None,
        to_channel_id: Optional[IntStr] = None,
        is_self_mute: bool = False,
        is_self_deaf: bool = False,
        is_server_mute: bool = False,
        is_server_deaf: bool = False,
    ) -> None:
        """
        VC_LOG/{vc_id}/members/{user_id}/events に 1 イベント追加。
        event_id は auto-id に任せる。
        """
        col_ref = self._events_col(vc_id, user_id)
        data: Dict[str, Any] = {
            "type": event_type,
            "ts": ts,
            "from_channel_id": str(from_channel_id) if from_channel_id is not None else None,
            "to_channel_id": str(to_channel_id) if to_channel_id is not None else None,
            "is_self_mute": is_self_mute,
            "is_self_deaf": is_self_deaf,
            "is_server_mute": is_server_mute,
            "is_server_deaf": is_server_deaf,
        }
        await self._q_add(col_ref, data)

    async def log_join(
        self,
        vc_id: IntStr,
        guild_id: IntStr,
        user_id: IntStr,
        ts: DatetimeWithNanoseconds,
        *,
        from_channel_id: Optional[IntStr] = None,
        is_self_mute: bool = False,
        is_self_deaf: bool = False,
        is_server_mute: bool = False,
        is_server_deaf: bool = False,
    ) -> None:
        """
        JOIN イベントを記録。
        - VC_LOG doc が無ければ作成
        - owner_user_id が未設定ならこのユーザーを owner に
        """
        await self.ensure_vc_doc(vc_id, guild_id, created_at=ts)
        await self.set_vc_owner_if_empty(vc_id, user_id)

        await self.add_event(
            vc_id=vc_id,
            user_id=user_id,
            event_type="JOIN",
            ts=ts,
            from_channel_id=from_channel_id,
            to_channel_id=vc_id,
            is_self_mute=is_self_mute,
            is_self_deaf=is_self_deaf,
            is_server_mute=is_server_mute,
            is_server_deaf=is_server_deaf,
        )

    async def log_leave(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        ts: DatetimeWithNanoseconds,
        *,
        to_channel_id: Optional[IntStr] = None,
        is_self_mute: bool = False,
        is_self_deaf: bool = False,
        is_server_mute: bool = False,
        is_server_deaf: bool = False,
    ) -> None:
        """
        LEAVE イベントを記録。
        """
        await self.add_event(
            vc_id=vc_id,
            user_id=user_id,
            event_type="LEAVE",
            ts=ts,
            from_channel_id=vc_id,
            to_channel_id=to_channel_id,
            is_self_mute=is_self_mute,
            is_self_deaf=is_self_deaf,
            is_server_mute=is_server_mute,
            is_server_deaf=is_server_deaf,
        )

    async def log_mute_on(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        ts: DatetimeWithNanoseconds,
        *,
        is_self_mute: bool = False,
        is_self_deaf: bool = False,
        is_server_mute: bool = False,
        is_server_deaf: bool = False,
    ) -> None:
        """
        MUTE_ON イベントを記録。
        """
        await self.add_event(
            vc_id=vc_id,
            user_id=user_id,
            event_type="MUTE_ON",
            ts=ts,
            is_self_mute=is_self_mute,
            is_self_deaf=is_self_deaf,
            is_server_mute=is_server_mute,
            is_server_deaf=is_server_deaf,
        )

    async def log_mute_off(
        self,
        vc_id: IntStr,
        user_id: IntStr,
        ts: DatetimeWithNanoseconds,
        *,
        is_self_mute: bool = False,
        is_self_deaf: bool = False,
        is_server_mute: bool = False,
        is_server_deaf: bool = False,
    ) -> None:
        """
        MUTE_OFF イベントを記録。
        """
        await self.add_event(
            vc_id=vc_id,
            user_id=user_id,
            event_type="MUTE_OFF",
            ts=ts,
            is_self_mute=is_self_mute,
            is_self_deaf=is_self_deaf,
            is_server_mute=is_server_mute,
            is_server_deaf=is_server_deaf,
        )

    # ------------- 読み出し（集計用） -------------

    async def fetch_member_ids(self, vc_id: IntStr) -> List[str]:
        """
        VC_LOG/{vc_id}/members 配下の user_id 一覧を返す。
        """
        members_col = self._vc_doc(vc_id).collection("members")
        user_ids: List[str] = []
        try:
            async for snap in members_col.stream():
                user_ids.append(snap.id)
        except Exception as e:
            logger.error(f"Error in fetch_member_ids({vc_id}): {e}")
        return user_ids

    async def fetch_events_for_member(self, vc_id: IntStr, user_id: IntStr) -> List[Dict[str, Any]]:
        """
        ある VC 内の、特定ユーザーの events を ts 昇順で取得。
        戻り値は dict のリスト（計算ロジック側で整形してOK）。
        """
        events_col = self._events_col(vc_id, user_id)
        events: List[Dict[str, Any]] = []
        try:
            query = events_col.order_by("ts")
            async for snap in query.stream():
                data = snap.to_dict() or {}
                events.append(data)
        except Exception as e:
            logger.error(f"Error in fetch_events_for_member(vc={vc_id}, user={user_id}): {e}")
        return events

    async def fetch_all_member_events(self, vc_id: IntStr) -> Dict[str, List[Dict[str, Any]]]:
        """
        VC 内の全ユーザーについて、そのユーザーのイベント一覧を取得して返す。
        形式: { user_id: [ {event}, {event}, ... ], ... }
        """
        result: Dict[str, List[Dict[str, Any]]] = {}
        members_col = self._vc_doc(vc_id).collection("members")

        try:
            async for member_snap in members_col.stream():
                user_id = member_snap.id
                result[user_id] = await self.fetch_events_for_member(vc_id, user_id)
        except Exception as e:
            logger.error(f"Error in fetch_all_member_events({vc_id}): {e}")

        return result

    # ------------- 後始末用（任意） -------------

    async def delete_vc_log(self, vc_id: IntStr) -> None:
        """
        必要に応じて VC_LOG/{vc_id} 以下をまるごと削除したいとき用。
        （本番運用では、ポイント付与後、一定期間でクリーンアップする想定）
        ※ コレクションの再帰削除は Firestore 上やや重いので注意。
        """
        await self._q_delete(self._vc_doc(vc_id))
