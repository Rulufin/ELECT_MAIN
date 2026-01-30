# fs_points.py
# ✅ Events(ledger) 1本化
# ✅ totals_by_event(map) / totals_by_genre(map)
# ✅ Points/{user_id} 直下に flat フィールドも保持（normal_vc_connect 等）
# ✅ メソッド名を record_event にして意図を明確化（add_points_method は互換 alias）
# ✅ 期間指定（Weekly / Monthly / All）で「確認集計」できる check_totals_by_period 追加
# ✅ end_ts は end_exclusive として "< end_ts" に統一

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union, Mapping

from zoneinfo import ZoneInfo

from google.cloud.firestore_v1 import AsyncClient
from google.cloud import firestore_v1 as firestore
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue
from utils.enum import Points_Type, Genre_Type

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateTimeLike = Union[datetime, DatetimeWithNanoseconds]


@dataclass(frozen=True)
class _DeltaPack:
    """
    トップ集計に入れる増減をまとめたもの。
    """
    total: int
    by_event: Dict[str, int]
    by_genre: Dict[str, int]
    flat_field: Optional[Tuple[str, int]] = None


class FS_Points:
    """
    汎用 Points（イベント台帳 / ledger）版。

    Firestore 構造:
    Points/{user_id}
      total_points: int
      totals_by_event: map[str]int
      totals_by_genre: map[str]int
      last_updated_at: Timestamp | None
      last_recalc_at: Timestamp | None
      (flat) normal_vc_connect: int
      (flat) normal_vc_owner: int
      ...

      Events/{event_id}
        ts: Timestamp
        date_ymd: str
        event_type: str
        genre: str
        delta: int  # +/- をここに入れる
        note?: str
        source?: map
        meta?: map
    """

    ROOT_COLLECTION = "Points"
    EVENTS_SUBCOLLECTION = "Events"
    TZ_JST = ZoneInfo("Asia/Tokyo")

    def __init__(
        self,
        root_collection: str = ROOT_COLLECTION,
        queue_manager=firestore_queue,
    ) -> None:
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")

        self.db: AsyncClient = client.firestore_db
        self.root = root_collection
        self.queue = queue_manager

    # ─────────────────────────
    # Firestore refs / queue wrappers
    # ─────────────────────────

    def _user_doc(self, user_id: IntStr):
        return self.db.collection(self.root).document(str(user_id))

    def _events_col(self, user_id: IntStr):
        return self._user_doc(user_id).collection(self.EVENTS_SUBCOLLECTION)

    async def _q(self, fn):
        try:
            return await self.queue.enqueue(fn)
        except Exception as e:
            logger.error(f"[FS_Points] queue error: {e}", exc_info=True)
            return None

    async def _q_get(self, doc_ref):
        # ✅ QueueManager が coroutinefunction 判定できるように async def を渡す
        async def _op():
            return await doc_ref.get()

        return await self._q(_op)

    async def _q_set(self, doc_ref, data: Dict[str, Any], *, merge: bool = True):
        # ✅ QueueManager が coroutinefunction 判定できるように async def を渡す
        async def _op():
            return await doc_ref.set(data, merge=merge)

        return await self._q(_op)

    # ─────────────────────────
    # normalize helpers
    # ─────────────────────────

    @staticmethod
    def _norm_event_type(event_type: Points_Type | str) -> str:
        # StrEnum は str(event_type) で value が返るが、明示的に統一
        return event_type.value if isinstance(event_type, Points_Type) else str(event_type)

    @staticmethod
    def _norm_genre(genre: Genre_Type | str) -> str:
        return genre.value if isinstance(genre, Genre_Type) else str(genre)

    # ─────────────────────────
    # datetime helpers
    # ─────────────────────────

    @classmethod
    def _to_jst(cls, ts: DateTimeLike) -> datetime:
        if isinstance(ts, DatetimeWithNanoseconds):
            dt = ts.replace(tzinfo=None)
            return dt.replace(tzinfo=cls.TZ_JST)

        if ts.tzinfo is None:
            return ts.replace(tzinfo=cls.TZ_JST)

        return ts.astimezone(cls.TZ_JST)

    @classmethod
    def extract_date_ymd(cls, ts: DateTimeLike) -> str:
        return cls._to_jst(ts).strftime("%Y%m%d")

    @classmethod
    def _floor_day(cls, dt: datetime) -> datetime:
        dt = dt.astimezone(cls.TZ_JST)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    @classmethod
    def build_period_range(
        cls,
        period: str,
        *,
        now: Optional[datetime] = None,
    ) -> Tuple[Optional[datetime], Optional[datetime], str]:
        """
        period: "Weekly" | "Monthly" | "All"
        returns: (start_inclusive, end_exclusive, label)

        - Weekly: 月曜00:00〜次週月曜00:00（= 月〜日）
        - Monthly: 当月1日00:00〜翌月1日00:00
        - All: None, None
        """
        p = str(period).strip()
        now_jst = (now or datetime.now(cls.TZ_JST)).astimezone(cls.TZ_JST)

        if p == "All":
            return None, None, "全体"

        if p == "Weekly":
            start = cls._floor_day(now_jst) - timedelta(days=now_jst.weekday())
            end = start + timedelta(days=7)
            return start, end, "今週（月〜日）"

        if p == "Monthly":
            start = cls._floor_day(now_jst).replace(day=1)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return start, end, "今月"

        # 想定外は All 扱い（必要なら ValueError にしてもOK）
        return None, None, f"不明({p})→全体"

    # ─────────────────────────
    # init / summary
    # ─────────────────────────

    async def init_user_if_needed(self, user_id: IntStr) -> None:
        snap = await self._q_get(self._user_doc(user_id))
        if snap and snap.exists:
            return

        init_data: Dict[str, Any] = {
            "total_points": 0,
            "totals_by_event": {},
            "totals_by_genre": {},
            "last_updated_at": None,
            "last_recalc_at": None,
        }
        await self._q_set(self._user_doc(user_id), init_data, merge=True)

    async def get_summary(self, user_id: IntStr) -> Dict[str, Any]:
        snap = await self._q_get(self._user_doc(user_id))
        if not snap or not snap.exists:
            return {}

        data = snap.to_dict() or {}
        return {
            "total_points": int(data.get("total_points", 0) or 0),
            "totals_by_event": dict(data.get("totals_by_event") or {}),
            "totals_by_genre": dict(data.get("totals_by_genre") or {}),
            "last_updated_at": data.get("last_updated_at"),
            "last_recalc_at": data.get("last_recalc_at"),
        }

    # ─────────────────────────
    # flat field name helper
    # ─────────────────────────

    @staticmethod
    def event_type_to_flat_field(event_type: str) -> str:
        """
        "Normal_VC_Connect" -> "normal_vc_connect"
        """
        s = event_type.strip()

        # "NormalVCConnect" みたいなのも救う
        s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)

        s = s.replace("-", "_").replace(" ", "_")
        s = re.sub(r"__+", "_", s)
        s = s.lower()
        s = re.sub(r"[^a-z0-9_]", "", s)

        return s or "unknown_event"

    # ─────────────────────────
    # deterministic event id
    # ─────────────────────────

    @classmethod
    def build_event_id(
        cls,
        *,
        ts: DateTimeLike,
        user_id: IntStr,
        event_type: str,
        genre: str,
        source: Optional[Mapping[str, Any]] = None,
        nonce: Optional[str] = None,
    ) -> str:
        """
        決定論的 event_id（同一入力→同一ID）
        - json(sort_keys=True) を使って安定化
        """
        dt = cls._to_jst(ts)
        ts_key = dt.strftime("%Y%m%d%H%M%S")  # 秒

        raw = {
            "user_id": str(user_id),
            "event_type": event_type,
            "genre": genre,
            "ts_key": ts_key,
            "source": dict(source or {}),
            "nonce": nonce or "",
        }
        raw_json = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(raw_json.encode("utf-8")).hexdigest()[:12]
        return f"{ts_key}_{digest}"

    # ─────────────────────────
    # internal: apply increments
    # ─────────────────────────

    async def _get_old_delta(self, doc_ref) -> int:
        snap = await self._q_get(doc_ref)
        if not snap or not snap.exists:
            return 0
        data = snap.to_dict() or {}
        return int(data.get("delta", 0) or 0)

    def _pack_delta(
        self,
        *,
        event_type: str,
        genre: str,
        diff: int,
        flat_field: Optional[str],
    ) -> _DeltaPack:
        flat = (flat_field, diff) if flat_field else None
        return _DeltaPack(
            total=diff,
            by_event={event_type: diff},
            by_genre={genre: diff},
            flat_field=flat,
        )

    async def _apply_increments(
        self,
        user_id: IntStr,
        *,
        pack: _DeltaPack,
        ts: DateTimeLike,
    ) -> None:
        updates: Dict[str, Any] = {}

        if pack.total != 0:
            updates["total_points"] = firestore.Increment(int(pack.total))

        for k, v in pack.by_event.items():
            if v != 0:
                updates[f"totals_by_event.{k}"] = firestore.Increment(int(v))

        for k, v in pack.by_genre.items():
            if v != 0:
                updates[f"totals_by_genre.{k}"] = firestore.Increment(int(v))

        if pack.flat_field is not None:
            field_name, v = pack.flat_field
            if v != 0:
                updates[field_name] = firestore.Increment(int(v))

        updates["last_updated_at"] = ts

        if updates:
            await self._q_set(self._user_doc(user_id), updates, merge=True)

    # ─────────────────────────
    # public: record event (main entry)
    # ─────────────────────────

    async def record_event(
        self,
        user_id: IntStr,
        *,
        event_type: Points_Type | str,
        genre: Genre_Type | str,
        delta: int,
        ts: DateTimeLike,
        # 任意情報
        note: Optional[str] = None,
        source: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
        # idempotency
        event_id: Optional[str] = None,
        nonce: Optional[str] = None,
        # flat field
        also_write_flat_field: bool = True,
        flat_field_override: Optional[str] = None,
    ) -> str:
        """
        1イベントを記録し、トップ集計を「差分」で更新する。

        delta:
          +30: 加点
          -10: 減点
        """
        delta = int(delta)
        if delta == 0:
            return event_id or "NOOP"

        await self.init_user_if_needed(user_id)

        et = self._norm_event_type(event_type)
        gn = self._norm_genre(genre)

        if event_id is None:
            event_id = self.build_event_id(
                ts=ts,
                user_id=user_id,
                event_type=et,
                genre=gn,
                source=source,
                nonce=nonce,
            )

        doc_ref = self._events_col(user_id).document(event_id)

        old_delta = await self._get_old_delta(doc_ref)
        diff = delta - old_delta
        if diff == 0:
            return event_id

        event_doc: Dict[str, Any] = {
            "ts": ts,
            "date_ymd": self.extract_date_ymd(ts),
            "event_type": et,
            "genre": gn,
            "delta": delta,
        }
        if note is not None:
            event_doc["note"] = note
        if source is not None:
            event_doc["source"] = dict(source)
        if meta is not None:
            event_doc["meta"] = dict(meta)

        # event_doc は上書き（矛盾を残さない）
        await self._q_set(doc_ref, event_doc, merge=False)

        flat_field: Optional[str] = None
        if also_write_flat_field:
            flat_field = flat_field_override or self.event_type_to_flat_field(et)

        pack = self._pack_delta(event_type=et, genre=gn, diff=diff, flat_field=flat_field)
        await self._apply_increments(user_id, pack=pack, ts=ts)

        return event_id

    # 互換: 旧名を残したい場合（不要なら消してOK）
    async def add_points_method(self, *args, **kwargs) -> str:  # type: ignore[override]
        return await self.record_event(*args, **kwargs)

    # ─────────────────────────
    # queries
    # ─────────────────────────

    async def list_events(
        self,
        user_id: IntStr,
        *,
        start_ts: Optional[DateTimeLike] = None,
        end_ts: Optional[DateTimeLike] = None,
        event_type: Optional[Points_Type | str] = None,
        genre: Optional[Genre_Type | str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        col = self._events_col(user_id)
        q = col

        if start_ts is not None:
            q = q.where("ts", ">=", start_ts)
        if end_ts is not None:
            q = q.where("ts", "<", end_ts)  # ✅ end_exclusive

        if event_type is not None:
            q = q.where("event_type", "==", self._norm_event_type(event_type))
        if genre is not None:
            q = q.where("genre", "==", self._norm_genre(genre))

        q = q.order_by("ts")

        out: List[Dict[str, Any]] = []
        try:
            async for snap in q.limit(int(limit)).stream():
                out.append(snap.to_dict() or {})
        except Exception as e:
            logger.error(f"[FS_Points] list_events error: {e}", exc_info=True)

        return out

    async def list_events_by_date(
        self,
        user_id: IntStr,
        *,
        date_ymd: str,
        event_type: Optional[Points_Type | str] = None,
        genre: Optional[Genre_Type | str] = None,
        limit: int = 400,
    ) -> List[Dict[str, Any]]:
        col = self._events_col(user_id)
        q = col.where("date_ymd", "==", date_ymd)

        if event_type is not None:
            q = q.where("event_type", "==", self._norm_event_type(event_type))
        if genre is not None:
            q = q.where("genre", "==", self._norm_genre(genre))

        q = q.order_by("ts")

        out: List[Dict[str, Any]] = []
        try:
            async for snap in q.limit(int(limit)).stream():
                out.append(snap.to_dict() or {})
        except Exception as e:
            logger.error(f"[FS_Points] list_events_by_date error: {e}", exc_info=True)

        return out

    # ─────────────────────────
    # calc/check (period verify)
    # ─────────────────────────

    async def calc_totals_in_range(
        self,
        user_id: IntStr,
        *,
        start_ts: Optional[DateTimeLike] = None,
        end_ts: Optional[DateTimeLike] = None,
        limit: int = 20000,
        also_flat: bool = True,
        only_flat_event_types: Optional[List[Points_Type | str]] = None,
    ) -> Dict[str, Any]:
        """
        Events を舐めて期間集計だけ返す（トップは更新しない）。
        end_ts は end_exclusive（< end_ts）
        """
        allow_flat: Optional[set[str]] = None
        if only_flat_event_types is not None:
            allow_flat = {self._norm_event_type(x) for x in only_flat_event_types}

        col = self._events_col(user_id)
        q = col
        if start_ts is not None:
            q = q.where("ts", ">=", start_ts)
        if end_ts is not None:
            q = q.where("ts", "<", end_ts)  # ✅ end_exclusive
        q = q.order_by("ts")

        total = 0
        by_event: Dict[str, int] = {}
        by_genre: Dict[str, int] = {}
        by_flat: Dict[str, int] = {}
        last_ts: Optional[DateTimeLike] = None

        try:
            i = 0
            async for snap in q.stream():
                i += 1
                if i > int(limit):
                    break

                d = snap.to_dict() or {}
                delta = int(d.get("delta", 0) or 0)
                et = str(d.get("event_type", "Unknown"))
                gn = str(d.get("genre", "Unknown"))
                ts = d.get("ts")

                total += delta
                by_event[et] = int(by_event.get(et, 0) or 0) + delta
                by_genre[gn] = int(by_genre.get(gn, 0) or 0) + delta

                if also_flat:
                    if allow_flat is None or et in allow_flat:
                        ff = self.event_type_to_flat_field(et)
                        by_flat[ff] = int(by_flat.get(ff, 0) or 0) + delta

                if ts is not None:
                    last_ts = ts

        except Exception as e:
            logger.error(f"[FS_Points] calc_totals_in_range error: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

        return {
            "ok": True,
            "total_points": total,
            "totals_by_event": by_event,
            "totals_by_genre": by_genre,
            "flat_totals": by_flat if also_flat else None,
            "last_ts": last_ts,
        }

    async def check_totals_by_period(
        self,
        user_id: IntStr,
        *,
        period: str,  # "Weekly" / "Monthly" / "All"
        limit: int = 20000,
        compare_with_top_when_all: bool = True,
    ) -> Dict[str, Any]:
        """
        period を受け取り、期間集計（確認用）を返す。
        All の場合はトップ集計とも突き合わせできる。
        """
        start, end, label = self.build_period_range(period)

        calc = await self.calc_totals_in_range(
            user_id,
            start_ts=start,
            end_ts=end,
            limit=limit,
            also_flat=True,
        )
        if not calc.get("ok"):
            return {"ok": False, "period": period, "label": label, "error": calc.get("error")}

        result: Dict[str, Any] = {
            "ok": True,
            "period": period,
            "label": label,
            "start_ts": start,
            "end_ts": end,
            "calc": calc,
        }

        if period == "All" and compare_with_top_when_all:
            top = await self.get_summary(user_id)

            def _as_int_map(x: Any) -> Dict[str, int]:
                m = dict(x or {})
                return {str(k): int(v or 0) for k, v in m.items()}

            mismatch = {
                "total_points": int(top.get("total_points", 0) or 0) != int(calc["total_points"]),
                "totals_by_event": _as_int_map(top.get("totals_by_event")) != _as_int_map(calc["totals_by_event"]),
                "totals_by_genre": _as_int_map(top.get("totals_by_genre")) != _as_int_map(calc["totals_by_genre"]),
            }

            result["top"] = top
            result["mismatch"] = mismatch
            result["is_consistent"] = not any(mismatch.values())

        return result

    # ─────────────────────────
    # recalc (rebuild totals)
    # ─────────────────────────

    async def recalc_user_totals(
        self,
        user_id: IntStr,
        *,
        start_ts: Optional[DateTimeLike] = None,
        end_ts: Optional[DateTimeLike] = None,
        limit: int = 20000,
        also_rebuild_flat_fields: bool = True,
        only_flat_event_types: Optional[List[Points_Type | str]] = None,
    ) -> Dict[str, Any]:
        """
        Events を舐めて totals を再計算し、トップへ上書き保存する（整合性担保用）。
        end_ts は end_exclusive（< end_ts）
        """
        await self.init_user_if_needed(user_id)

        allow_flat: Optional[set[str]] = None
        if only_flat_event_types is not None:
            allow_flat = {self._norm_event_type(x) for x in only_flat_event_types}

        col = self._events_col(user_id)
        q = col
        if start_ts is not None:
            q = q.where("ts", ">=", start_ts)
        if end_ts is not None:
            q = q.where("ts", "<", end_ts)  # ✅ end_exclusive
        q = q.order_by("ts")

        total = 0
        by_event: Dict[str, int] = {}
        by_genre: Dict[str, int] = {}
        by_flat: Dict[str, int] = {}

        last_ts: Optional[DateTimeLike] = None

        try:
            i = 0
            async for snap in q.stream():
                i += 1
                if i > int(limit):
                    break

                d = snap.to_dict() or {}
                delta = int(d.get("delta", 0) or 0)
                et = str(d.get("event_type", "Unknown"))
                gn = str(d.get("genre", "Unknown"))
                ts = d.get("ts")

                total += delta
                by_event[et] = int(by_event.get(et, 0) or 0) + delta
                by_genre[gn] = int(by_genre.get(gn, 0) or 0) + delta

                if also_rebuild_flat_fields:
                    if allow_flat is None or et in allow_flat:
                        ff = self.event_type_to_flat_field(et)
                        by_flat[ff] = int(by_flat.get(ff, 0) or 0) + delta

                if ts is not None:
                    last_ts = ts

        except Exception as e:
            logger.error(f"[FS_Points] recalc_user_totals error: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

        now = datetime.now(self.TZ_JST)

        updates: Dict[str, Any] = {
            "total_points": int(total),
            "totals_by_event": by_event,
            "totals_by_genre": by_genre,
            "last_recalc_at": now,
            "last_updated_at": last_ts or now,
        }

        # フラットフィールド rebuild（古い不要フィールドの削除まではしない）
        if also_rebuild_flat_fields:
            updates.update(by_flat)

        await self._q_set(self._user_doc(user_id), updates, merge=True)

        return {
            "ok": True,
            "total_points": total,
            "totals_by_event": by_event,
            "totals_by_genre": by_genre,
            "flat_totals": by_flat if also_rebuild_flat_fields else None,
        }
