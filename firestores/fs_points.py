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
from google.cloud.firestore_v1.base_query import FieldFilter
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase
from utils.enum import Points_Type, Genre_Type

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateTimeLike = Union[datetime, DatetimeWithNanoseconds]


@dataclass(frozen=True)
class _DeltaPack:
    total: int
    by_event: Dict[str, int]
    by_genre: Dict[str, int]
    flat_field: Optional[Tuple[str, int]] = None


class FS_Points(FirestoreBase):
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
      ...

      Events/{event_id}
        ts: Timestamp
        date_ymd: str
        event_type: str
        genre: str
        delta: int
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

        super().__init__(queue_manager)
        self.root = root_collection

    # ─────────────────────────
    # Firestore refs
    # ─────────────────────────

    def _user_doc(self, user_id: IntStr):
        return self.db.collection(self.root).document(str(user_id))

    def _events_col(self, user_id: IntStr):
        return self._user_doc(user_id).collection(self.EVENTS_SUBCOLLECTION)

    # ─────────────────────────
    # normalize helpers
    # ─────────────────────────

    @staticmethod
    def _norm_event_type(event_type: Points_Type | str) -> str:
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

        return None, None, f"不明({p})→全体"

    # ─────────────────────────
    # flat field name helper
    # ─────────────────────────

    @staticmethod
    def event_type_to_flat_field(event_type: str) -> str:
        s = event_type.strip()
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
        dt = cls._to_jst(ts)
        ts_key = dt.strftime("%Y%m%d%H%M%S")

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
    # internal helpers
    # (_run の中から呼ばれる前提。Firestore を直接呼ぶ)
    # ─────────────────────────

    async def _get_old_delta(self, doc_ref) -> int:
        snap = await doc_ref.get()
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
            await self._user_doc(user_id).update(updates)

    # ─────────────────────────
    # init / summary
    # ─────────────────────────

    async def init_user_if_needed(self, user_id: IntStr) -> None:
        async def runner():
            return await self._init_user_if_needed(user_id)
        try:
            await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_Points] init_user_if_needed queue error: {e}", exc_info=True)

    async def _init_user_if_needed(self, user_id: IntStr) -> None:
        snap = await self._user_doc(user_id).get()
        if snap and snap.exists:
            return

        init_data: Dict[str, Any] = {
            "total_points": 0,
            "totals_by_event": {},
            "totals_by_genre": {},
            "last_updated_at": None,
            "last_recalc_at": None,
        }
        await self._user_doc(user_id).set(init_data, merge=True)

    async def get_summary(self, user_id: IntStr) -> Dict[str, Any]:
        async def runner():
            return await self._get_summary(user_id)
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Points] get_summary queue error: {e}", exc_info=True)
            return {}

    async def _get_summary(self, user_id: IntStr) -> Dict[str, Any]:
        snap = await self._user_doc(user_id).get()
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
    # record event
    # ─────────────────────────

    async def record_event(
        self,
        user_id: IntStr,
        *,
        event_type: Points_Type | str,
        genre: Genre_Type | str,
        delta: int,
        ts: DateTimeLike,
        note: Optional[str] = None,
        source: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
        nonce: Optional[str] = None,
        also_write_flat_field: bool = True,
        flat_field_override: Optional[str] = None,
    ) -> str:
        async def runner():
            return await self._record_event(
                user_id,
                event_type=event_type,
                genre=genre,
                delta=delta,
                ts=ts,
                note=note,
                source=source,
                meta=meta,
                event_id=event_id,
                nonce=nonce,
                also_write_flat_field=also_write_flat_field,
                flat_field_override=flat_field_override,
            )
        try:
            return await self._run(runner) or ""
        except Exception as e:
            logger.error(f"[FS_Points] record_event queue error: {e}", exc_info=True)
            return ""

    async def _record_event(
        self,
        user_id: IntStr,
        *,
        event_type: Points_Type | str,
        genre: Genre_Type | str,
        delta: int,
        ts: DateTimeLike,
        note: Optional[str] = None,
        source: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
        nonce: Optional[str] = None,
        also_write_flat_field: bool = True,
        flat_field_override: Optional[str] = None,
    ) -> str:
        delta = int(delta)
        if delta == 0:
            return event_id or "NOOP"

        await self._init_user_if_needed(user_id)

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

        await doc_ref.set(event_doc, merge=False)

        flat_field: Optional[str] = None
        if also_write_flat_field:
            flat_field = flat_field_override or self.event_type_to_flat_field(et)

        pack = self._pack_delta(event_type=et, genre=gn, diff=diff, flat_field=flat_field)
        await self._apply_increments(user_id, pack=pack, ts=ts)

        return event_id

    async def add_points_method(self, *args, **kwargs) -> str:
        return await self.record_event(*args, **kwargs)

    async def delete_event(self, user_id: IntStr, event_id: str) -> bool:
        async def runner():
            return await self._delete_event(user_id, event_id)
        try:
            return await self._run(runner) or False
        except Exception as e:
            logger.error(f"[FS_Points] delete_event queue error: {e}", exc_info=True)
            return False

    async def _delete_event(self, user_id: IntStr, event_id: str) -> bool:
        try:
            doc_ref = self._events_col(user_id).document(event_id)
            snap = await doc_ref.get()
            if snap.exists:
                await doc_ref.delete()
            return True
        except Exception as e:
            logger.error(f"[FS_Points] _delete_event failed: {e}", exc_info=True)
            return False

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
        async def runner():
            return await self._list_events(
                user_id,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type=event_type,
                genre=genre,
                limit=limit,
            )
        try:
            return await self._run(runner) or []
        except Exception as e:
            logger.error(f"[FS_Points] list_events queue error: {e}", exc_info=True)
            return []

    async def _list_events(
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
            q = q.where(filter=FieldFilter("ts", ">=", start_ts))
        if end_ts is not None:
            q = q.where(filter=FieldFilter("ts", "<", end_ts))

        if event_type is not None:
            q = q.where(filter=FieldFilter("event_type", "==", self._norm_event_type(event_type)))
        if genre is not None:
            q = q.where(filter=FieldFilter("genre", "==", self._norm_genre(genre)))

        q = q.order_by("ts")

        out: List[Dict[str, Any]] = []
        try:
            async for snap in q.limit(int(limit)).stream():
                out.append(snap.to_dict() or {})
        except Exception as e:
            logger.error(f"[FS_Points] _list_events error: {e}", exc_info=True)

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
        async def runner():
            return await self._list_events_by_date(
                user_id,
                date_ymd=date_ymd,
                event_type=event_type,
                genre=genre,
                limit=limit,
            )
        try:
            return await self._run(runner) or []
        except Exception as e:
            logger.error(f"[FS_Points] list_events_by_date queue error: {e}", exc_info=True)
            return []

    async def _list_events_by_date(
        self,
        user_id: IntStr,
        *,
        date_ymd: str,
        event_type: Optional[Points_Type | str] = None,
        genre: Optional[Genre_Type | str] = None,
        limit: int = 400,
    ) -> List[Dict[str, Any]]:
        col = self._events_col(user_id)
        q = col.where(filter=FieldFilter("date_ymd", "==", date_ymd))

        if event_type is not None:
            q = q.where(filter=FieldFilter("event_type", "==", self._norm_event_type(event_type)))
        if genre is not None:
            q = q.where(filter=FieldFilter("genre", "==", self._norm_genre(genre)))

        q = q.order_by("ts")

        out: List[Dict[str, Any]] = []
        try:
            async for snap in q.limit(int(limit)).stream():
                out.append(snap.to_dict() or {})
        except Exception as e:
            logger.error(f"[FS_Points] _list_events_by_date error: {e}", exc_info=True)

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
        async def runner():
            return await self._calc_totals_in_range(
                user_id,
                start_ts=start_ts,
                end_ts=end_ts,
                limit=limit,
                also_flat=also_flat,
                only_flat_event_types=only_flat_event_types,
            )
        try:
            return await self._run(runner) or {"ok": False, "error": "no result"}
        except Exception as e:
            logger.error(f"[FS_Points] calc_totals_in_range queue error: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    async def _calc_totals_in_range(
        self,
        user_id: IntStr,
        *,
        start_ts: Optional[DateTimeLike] = None,
        end_ts: Optional[DateTimeLike] = None,
        limit: int = 20000,
        also_flat: bool = True,
        only_flat_event_types: Optional[List[Points_Type | str]] = None,
    ) -> Dict[str, Any]:
        allow_flat: Optional[set[str]] = None
        if only_flat_event_types is not None:
            allow_flat = {self._norm_event_type(x) for x in only_flat_event_types}

        col = self._events_col(user_id)
        q = col
        if start_ts is not None:
            q = q.where(filter=FieldFilter("ts", ">=", start_ts))
        if end_ts is not None:
            q = q.where(filter=FieldFilter("ts", "<", end_ts))
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
            logger.error(f"[FS_Points] _calc_totals_in_range error: {e}", exc_info=True)
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
        period: str,
        limit: int = 20000,
        compare_with_top_when_all: bool = True,
    ) -> Dict[str, Any]:
        async def runner():
            return await self._check_totals_by_period(
                user_id,
                period=period,
                limit=limit,
                compare_with_top_when_all=compare_with_top_when_all,
            )
        try:
            return await self._run(runner) or {"ok": False, "error": "no result"}
        except Exception as e:
            logger.error(f"[FS_Points] check_totals_by_period queue error: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    async def _check_totals_by_period(
        self,
        user_id: IntStr,
        *,
        period: str,
        limit: int = 20000,
        compare_with_top_when_all: bool = True,
    ) -> Dict[str, Any]:
        start, end, label = self.build_period_range(period)

        calc = await self._calc_totals_in_range(
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
            top = await self._get_summary(user_id)

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
        async def runner():
            return await self._recalc_user_totals(
                user_id,
                start_ts=start_ts,
                end_ts=end_ts,
                limit=limit,
                also_rebuild_flat_fields=also_rebuild_flat_fields,
                only_flat_event_types=only_flat_event_types,
            )
        try:
            return await self._run(runner) or {"ok": False, "error": "no result"}
        except Exception as e:
            logger.error(f"[FS_Points] recalc_user_totals queue error: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    async def _recalc_user_totals(
        self,
        user_id: IntStr,
        *,
        start_ts: Optional[DateTimeLike] = None,
        end_ts: Optional[DateTimeLike] = None,
        limit: int = 20000,
        also_rebuild_flat_fields: bool = True,
        only_flat_event_types: Optional[List[Points_Type | str]] = None,
    ) -> Dict[str, Any]:
        await self._init_user_if_needed(user_id)

        allow_flat: Optional[set[str]] = None
        if only_flat_event_types is not None:
            allow_flat = {self._norm_event_type(x) for x in only_flat_event_types}

        col = self._events_col(user_id)
        q = col
        if start_ts is not None:
            q = q.where(filter=FieldFilter("ts", ">=", start_ts))
        if end_ts is not None:
            q = q.where(filter=FieldFilter("ts", "<", end_ts))
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
            logger.error(f"[FS_Points] _recalc_user_totals error: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

        now = datetime.now(self.TZ_JST)

        updates: Dict[str, Any] = {
            "total_points": int(total),
            "totals_by_event": by_event,
            "totals_by_genre": by_genre,
            "last_recalc_at": now,
            "last_updated_at": last_ts or now,
        }

        if also_rebuild_flat_fields:
            updates.update(by_flat)

        await self._user_doc(user_id).set(updates, merge=True)

        return {
            "ok": True,
            "total_points": total,
            "totals_by_event": by_event,
            "totals_by_genre": by_genre,
            "flat_totals": by_flat if also_rebuild_flat_fields else None,
        }

    # ─────────────────────────
    # all users totals
    # ─────────────────────────

    async def list_all_user_totals(
        self,
        *,
        limit: int = 5000,
        order_desc: bool = True,
        include_zero: bool = True,
    ) -> List[Dict[str, Any]]:
        async def runner():
            return await self._list_all_user_totals(
                limit=limit,
                order_desc=order_desc,
                include_zero=include_zero,
            )
        try:
            return await self._run(runner) or []
        except Exception as e:
            logger.error(f"[FS_Points] list_all_user_totals queue error: {e}", exc_info=True)
            return []

    async def _list_all_user_totals(
        self,
        *,
        limit: int = 5000,
        order_desc: bool = True,
        include_zero: bool = True,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []

        try:
            direction = (
                firestore.Query.DESCENDING
                if order_desc
                else firestore.Query.ASCENDING
            )
            q = self.db.collection(self.root).order_by("total_points", direction=direction)

            i = 0
            async for snap in q.stream():
                i += 1
                if i > int(limit):
                    break

                data = snap.to_dict() or {}
                total_points = int(data.get("total_points", 0) or 0)

                if not include_zero and total_points == 0:
                    continue

                out.append(
                    {
                        "user_id": str(snap.id),
                        "total_points": total_points,
                        "last_updated_at": data.get("last_updated_at"),
                        "last_recalc_at": data.get("last_recalc_at"),
                    }
                )

        except Exception as e:
            logger.error(f"[FS_Points] _list_all_user_totals error: {e}", exc_info=True)

        return out

    async def list_all_user_totals_map(
        self,
        *,
        limit: int = 5000,
        include_zero: bool = True,
    ) -> Dict[str, int]:
        async def runner():
            return await self._list_all_user_totals_map(
                limit=limit,
                include_zero=include_zero,
            )
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Points] list_all_user_totals_map queue error: {e}", exc_info=True)
            return {}

    async def _list_all_user_totals_map(
        self,
        *,
        limit: int = 5000,
        include_zero: bool = True,
    ) -> Dict[str, int]:
        rows = await self._list_all_user_totals(
            limit=limit,
            order_desc=True,
            include_zero=include_zero,
        )
        return {
            str(row["user_id"]): int(row.get("total_points", 0) or 0)
            for row in rows
        }

    # ─────────────────────────
    # migration
    # ─────────────────────────

    async def migrate_fix_dotted_fields(self) -> Dict[str, Any]:
        """
        _apply_increments が .set() で誤生成した dotted literal fields（例: totals_by_genre.VC）を
        削除し、全ユーザーの totals を Events から再計算する。
        FieldPath を使わず、ドット入りキーを除いた clean data で set() 完全上書きする。
        """
        user_count = 0
        cleaned_total = 0

        async for snap in self.db.collection(self.root).stream():
            user_id = snap.id
            data = snap.to_dict() or {}

            stale_keys = [k for k in data.keys() if "." in k]

            if stale_keys:
                clean_data = {k: v for k, v in data.items() if "." not in k}

                async def _overwrite(ref=snap.reference, cd=clean_data):
                    await ref.set(cd)

                await self._run(_overwrite)
                cleaned_total += len(stale_keys)

            await self.recalc_user_totals(user_id)
            user_count += 1

        return {"ok": True, "user_count": user_count, "cleaned_fields": cleaned_total}
