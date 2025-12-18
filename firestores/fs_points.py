import logging
from typing import Any, Dict, List, Optional, Union

from datetime import datetime
from zoneinfo import ZoneInfo

from google.cloud.firestore_v1 import AsyncClient
from google.cloud import firestore_v1 as firestore  # noqa: F401  # Increment などで利用
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateTimeLike = Union[datetime, DatetimeWithNanoseconds]


class FS_Points:
    """
    Points コレクションを扱う Firestore I/O クラス。

    構造イメージ:
    (default)
    ┗ Points
       ┗ {user_id}
          ┣ meta (Map)
          ┣ VC_Owner   (SubCollection)
          │  ┗ {event_id}  # "YYYYMMDDHHMMSS_{vc_id}"
          │     ┣ ts_awarded: Timestamp
          │     ┣ date_ymd: str      # "YYYYMMDD"
          │     ┣ vc_id: str
          │     ┣ point: int
          │     ┗ note: str (optional)
          ┗ VC_Connect (SubCollection)
             ┗ {event_id}  # 同上
                ┣ ts_awarded: Timestamp
                ┣ date_ymd: str
                ┣ vc_id: str
                ┣ point: int
                ┗ note: str (optional)
    """

    ROOT_COLLECTION = "Points"
    TZ_JST = ZoneInfo("Asia/Tokyo")

    def __init__(
        self,
        root_collection: str = "Points",
        queue_manager=firestore_queue,  # QueueManager_FireStore インスタンス想定
    ):
        # Firestoreクライアント
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")
        self.db: AsyncClient = client.firestore_db
        self.root = root_collection

        # Firestoreキュー
        self.queue = queue_manager

    # ------------- internal helpers -------------

    def _user_doc(self, user_id: IntStr):
        return self.db.collection(self.root).document(str(user_id))

    def _event_col(self, user_id: IntStr, event_name: str):
        """
        event_name: "VC_Owner" / "VC_Connect" など
        """
        return self._user_doc(user_id).collection(event_name)

    # --- queue wrappers ---

    async def _q_get(self, doc_ref):
        async def get_doc():
            return await doc_ref.get()

        try:
            return await self.queue.enqueue(get_doc)
        except Exception as e:
            logger.error(f"Error in FS_Points._q_get: {e}")
            return None

    async def _q_set(self, doc_ref, data: Dict[str, Any], merge: bool = True):
        async def set_doc():
            return await doc_ref.set(data, merge=merge)

        try:
            return await self.queue.enqueue(set_doc)
        except Exception as e:
            logger.error(f"Error in FS_Points._q_set: {e}")
            return None

    # ------------- meta 操作 -------------

    async def get_meta(self, user_id: IntStr) -> Dict[str, Any]:
        """
        Points/{user_id}.meta を dict で返す。存在しなければ {}。
        """
        doc_ref = self._user_doc(user_id)
        snap = await self._q_get(doc_ref)
        if not snap or not snap.exists:
            return {}
        data = snap.to_dict() or {}
        return dict(data.get("meta", {}) or {})

    async def init_user_if_needed(self, user_id: IntStr) -> None:
        """
        Points/{user_id} が存在しなければ、meta を 0 初期化する。
        """
        doc_ref = self._user_doc(user_id)
        snap = await self._q_get(doc_ref)
        if snap and snap.exists:
            return

        meta: Dict[str, Any] = {
            "total_points": 0,
            "owner_total": 0,
            "connect_total": 0,
            "last_updated_at": None,
        }
        await self._q_set(doc_ref, {"meta": meta}, merge=True)

    async def update_meta(
        self,
        user_id: IntStr,
        *,
        delta_total: int = 0,
        delta_owner: int = 0,
        delta_connect: int = 0,
        ts: Optional[DateTimeLike] = None,
    ) -> None:
        """
        meta のカウンタをインクリメント更新する。
        ※ delta_* が 0 の場合はそのフィールドは変更しない。
        """
        doc_ref = self._user_doc(user_id)

        # 必要ならユーザー初期化
        await self.init_user_if_needed(user_id)

        updates: Dict[str, Any] = {}
        if delta_total != 0:
            updates["meta.total_points"] = firestore.Increment(delta_total)
        if delta_owner != 0:
            updates["meta.owner_total"] = firestore.Increment(delta_owner)
        if delta_connect != 0:
            updates["meta.connect_total"] = firestore.Increment(delta_connect)

        if ts is not None:
            updates["meta.last_updated_at"] = ts

        if not updates:
            return

        await self._q_set(doc_ref, updates, merge=True)

    # ------------- 日付 / event_id 生成 -------------

    @classmethod
    def _to_jst(cls, ts: DateTimeLike) -> datetime:
        """
        渡された datetime / Firestore Timestamp を JST に正規化する。
        naive の場合は JST とみなして tzinfo を付与。
        """
        if isinstance(ts, DatetimeWithNanoseconds):
            dt = ts.replace(tzinfo=None)  # DatetimeWithNanosecondsはtzinfo無しが多い
            dt = dt.replace(tzinfo=cls.TZ_JST)
            return dt
        if ts.tzinfo is None:
            return ts.replace(tzinfo=cls.TZ_JST)
        return ts.astimezone(cls.TZ_JST)

    @classmethod
    def build_event_id(cls, ts_awarded: DateTimeLike, vc_id: IntStr) -> str:
        """
        "YYYYMMDDHHMMSS_{vc_id}" 形式の event_id を生成する。
        """
        dt = cls._to_jst(ts_awarded)
        ymdhms = dt.strftime("%Y%m%d%H%M%S")
        return f"{ymdhms}_{vc_id}"

    @classmethod
    def extract_date_ymd(cls, ts_awarded: DateTimeLike) -> str:
        """
        "YYYYMMDD" 形式の date_ymd を返す。
        """
        dt = cls._to_jst(ts_awarded)
        return dt.strftime("%Y%m%d")

    # ------------- イベント追加 (VC_Owner / VC_Connect) -------------

    async def _upsert_event_and_meta(
        self,
        *,
        user_id: IntStr,
        event_name: str,
        vc_id: IntStr,
        ts_awarded: DateTimeLike,
        point: int,
        note: Optional[str] = None,
        meta_owner: bool = False,
        meta_connect: bool = False,
    ) -> None:
        """
        内部共通:
        - Points/{user_id}/{event_name}/{event_id} を upsert
        - 差分 delta を計算して meta をインクリメント
        """
        if point == 0:
            return

        await self.init_user_if_needed(user_id)

        event_col = self._event_col(user_id, event_name)
        event_id = self.build_event_id(ts_awarded, vc_id)
        date_ymd = self.extract_date_ymd(ts_awarded)

        doc_ref = event_col.document(event_id)

        # 既存のポイントがあれば差分にする（再実行に強くするため）
        snap = await self._q_get(doc_ref)
        old_point = 0
        if snap and snap.exists:
            data = snap.to_dict() or {}
            old_point = int(data.get("point", 0))

        # 差分（新 - 旧）
        delta = point - old_point
        if delta == 0 and snap and snap.exists:
            # ポイントが変化していないなら何もせず終了
            return

        event_data: Dict[str, Any] = {
            "ts_awarded": ts_awarded,
            "date_ymd": date_ymd,
            "vc_id": str(vc_id),
            "point": point,
        }
        if note is not None:
            event_data["note"] = note

        # イベントドキュメントを上書き
        await self._q_set(doc_ref, event_data, merge=False)

        # meta 更新
        delta_total = delta
        delta_owner = delta if meta_owner else 0
        delta_connect = delta if meta_connect else 0

        await self.update_meta(
            user_id,
            delta_total=delta_total,
            delta_owner=delta_owner,
            delta_connect=delta_connect,
            ts=ts_awarded,
        )

    async def add_owner_points(
        self,
        user_id: IntStr,
        *,
        vc_id: IntStr,
        ts_awarded: DateTimeLike,
        point: int,
        note: Optional[str] = None,
    ) -> None:
        """
        部屋主ボーナス (VC_Owner) のポイントを追加（または更新）する。

        - event_id = "YYYYMMDDHHMMSS_{vc_id}"
        - 再実行時は差分だけ meta に反映される
        """
        try:
            await self._upsert_event_and_meta(
                user_id=user_id,
                event_name="VC_Owner",
                vc_id=vc_id,
                ts_awarded=ts_awarded,
                point=point,
                note=note,
                meta_owner=True,
                meta_connect=False,
            )
        except Exception as e:
            logger.error(f"Error in add_owner_points(user={user_id}, vc={vc_id}): {e}")

    async def add_connect_points(
        self,
        user_id: IntStr,
        *,
        vc_id: IntStr,
        ts_awarded: DateTimeLike,
        point: int,
        note: Optional[str] = None,
    ) -> None:
        """
        接続時間ポイント (VC_Connect) を追加（または更新）する。
        """
        try:
            await self._upsert_event_and_meta(
                user_id=user_id,
                event_name="VC_Connect",
                vc_id=vc_id,
                ts_awarded=ts_awarded,
                point=point,
                note=note,
                meta_owner=False,
                meta_connect=True,
            )
        except Exception as e:
            logger.error(f"Error in add_connect_points(user={user_id}, vc={vc_id}): {e}")

    # ------------- 参照系（振り返り用） -------------

    async def list_events(
        self,
        user_id: IntStr,
        event_name: str,
        *,
        start_ts: Optional[DateTimeLike] = None,
        end_ts: Optional[DateTimeLike] = None,
    ) -> List[Dict[str, Any]]:
        """
        指定ユーザー・指定イベント種別のイベントログを取得する。

        event_name: "VC_Owner" or "VC_Connect"
        start_ts / end_ts が指定されていれば ts_awarded の範囲でフィルタ。
        """
        col_ref = self._event_col(user_id, event_name)
        events: List[Dict[str, Any]] = []

        try:
            query = col_ref
            if start_ts is not None:
                query = query.where("ts_awarded", ">=", start_ts)
            if end_ts is not None:
                query = query.where("ts_awarded", "<=", end_ts)
            query = query.order_by("ts_awarded")

            async for snap in query.stream():
                events.append(snap.to_dict() or {})
        except Exception as e:
            logger.error(f"Error in list_events(user={user_id}, event={event_name}): {e}")

        return events

    async def list_events_by_date(
        self,
        user_id: IntStr,
        event_name: str,
        date_ymd: str,
    ) -> List[Dict[str, Any]]:
        """
        指定ユーザー・指定イベント種別・指定日付(YYYYMMDD) のイベントを取得する。
        """
        col_ref = self._event_col(user_id, event_name)
        events: List[Dict[str, Any]] = []

        try:
            query = col_ref.where("date_ymd", "==", date_ymd).order_by("ts_awarded")
            async for snap in query.stream():
                events.append(snap.to_dict() or {})
        except Exception as e:
            logger.error(
                f"Error in list_events_by_date(user={user_id}, event={event_name}, date_ymd={date_ymd}): {e}"
            )

        return events
