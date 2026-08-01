from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from zoneinfo import ZoneInfo
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from firestores.fs_voice_log import FS_Voice_Log
from firestores.fs_points import FS_Points
from utils.enum import Genre_Type, Points_Type

from .rules import VC_POINT_RULES, VC_Point_Rule
from .resolvers import (
    resolve_points_type_for_connect,
    resolve_points_type_for_owner,
    resolve_vc_type_from_category,
)

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateTimeLike = Union[datetime, DatetimeWithNanoseconds]

TZ_JST = ZoneInfo("Asia/Tokyo")


@dataclass
class UserVoiceStateForCalc:
    """
    集計用の一時状態（1ユーザー分）。
    """
    in_vc: bool = False
    muted: bool = False
    current_unmute_start: Optional[datetime] = None
    total_unmuted_msec: int = 0


class VoicePointCalculator:
    """
    VC_LOG を元に、VC削除時にポイントを計算して Points に書き込むロジッククラス。

    前提:
    - category_id は VC_LOG/{vc_id} トップに保存されている
    - mute / deaf の扱いは VC_POINT_RULES 側で切り替える
    - 0pt のイベントは保存しない
    - points_calculated は 0pt でも必ず立てる
    """

    def __init__(
        self,
        fs_voice_log: Optional[FS_Voice_Log] = None,
        fs_points: Optional[FS_Points] = None,
    ):
        self.fs_voice_log = fs_voice_log or FS_Voice_Log()
        self.fs_points = fs_points or FS_Points()
        self.tz = TZ_JST

    # ─────────────────────────
    # public
    # ─────────────────────────

    async def process_vc_closed(self, vc_id: IntStr) -> None:
        """
        VC削除時のメイン処理。
        """
        vc_id_str = str(vc_id)

        try:
            if await self.fs_voice_log.is_points_calculated(vc_id_str):
                logger.info("[VoicePointCalculator] VC %s already points_calculated, skip.", vc_id_str)
                return

            payload = await self.fs_voice_log.fetch_vc_all(vc_id_str, include_event_doc_id=False)
            vc_doc = payload.get("vc") or {}
            members = payload.get("members") or {}

            if not vc_doc:
                logger.warning("[VoicePointCalculator] VC doc not found for vc_id=%s.", vc_id_str)
                return

            created_at_raw = vc_doc.get("created_at")
            deleted_at_raw = vc_doc.get("deleted_at")
            owner_user_id = vc_doc.get("owner_user_id")

            category_id = self._coerce_int(vc_doc.get("category_id"))
            vc_type = resolve_vc_type_from_category(category_id)
            if vc_type is None:
                logger.warning(
                    "[VoicePointCalculator] vc=%s category_id=%s => vc_type unresolved. skip.",
                    vc_id_str,
                    category_id,
                )
                return

            deleted_at = (
                self._to_jst(deleted_at_raw)
                if deleted_at_raw is not None
                else datetime.now(self.tz)
            )
            created_at = (
                self._to_jst(created_at_raw)
                if created_at_raw is not None
                else None
            )

            rule: VC_Point_Rule = VC_POINT_RULES[vc_type].resolve(created_at or deleted_at)

            events_per_user = self._build_events_per_user(members)

            unmuted_msec_per_user = self.calc_unmuted_time_per_user(
                events_per_user=events_per_user,
                deleted_at=deleted_at,
                include_mic_mute=bool(rule.include_mic_mute),
                include_speaker_mute=bool(rule.include_speaker_mute),
            )

            num_users_at_threshold = 0
            if created_at is not None and rule.has_owner_bonus():
                num_users_at_threshold = self.calc_users_at_minutes(
                    events_per_user=events_per_user,
                    created_at=created_at,
                    deleted_at=deleted_at,
                    minutes=int(rule.owner_threshold_min or 0),
                )

            owner_points, connect_points_per_user = self.calc_points(
                unmuted_msec_per_user=unmuted_msec_per_user,
                num_users_at_threshold=num_users_at_threshold,
                owner_user_id=str(owner_user_id) if owner_user_id else None,
                rule=rule,
            )

            ts_awarded = datetime.fromtimestamp(deleted_at.timestamp(), tz=self.tz)
            vc_type_value = getattr(vc_type, "value", str(vc_type))
            base_note = f"vc_type={vc_type_value} category_id={category_id}"

            connect_event_type = resolve_points_type_for_connect(vc_type)

            owner_event_type: Optional[Points_Type] = None
            if rule.has_owner_bonus():
                owner_event_type = resolve_points_type_for_owner(vc_type)

            owner_saved = await self._save_owner_points(
                vc_id_str=vc_id_str,
                owner_user_id=str(owner_user_id) if owner_user_id else None,
                owner_event_type=owner_event_type,
                owner_points=owner_points,
                num_users_at_threshold=num_users_at_threshold,
                rule=rule,
                ts_awarded=ts_awarded,
                category_id=category_id,
                vc_type_value=vc_type_value,
                base_note=base_note,
            )

            connect_saved_count = await self._save_connect_points(
                vc_id_str=vc_id_str,
                connect_points_per_user=connect_points_per_user,
                connect_event_type=connect_event_type,
                rule=rule,
                ts_awarded=ts_awarded,
                category_id=category_id,
                vc_type_value=vc_type_value,
                base_note=base_note,
            )

            if connect_saved_count == 0:
                logger.info(
                    "[VoicePointCalculator] VC %s connect: no eligible members (block unmet). skip all connect awards.",
                    vc_id_str,
                )

            if (
                not owner_saved
                and owner_event_type is not None
                and owner_user_id
                and num_users_at_threshold <= 0
            ):
                logger.info(
                    "[VoicePointCalculator] VC %s owner: users_at_threshold=0, owner bonus skipped.",
                    vc_id_str,
                )

            await self.fs_voice_log.mark_points_calculated(
                vc_id_str,
                ts=ts_awarded,
                meta={
                    "vc_type": vc_type_value,
                    "category_id": category_id,
                    "owner_saved": owner_saved,
                    "connect_saved_count": connect_saved_count,
                    "users_at_threshold": num_users_at_threshold,
                },
            )

            logger.info(
                "[VoicePointCalculator] Processed VC %s: type=%s category_id=%s owner=%s owner_points=%s connect_saved=%s",
                vc_id_str,
                vc_type_value,
                category_id,
                owner_user_id,
                owner_points,
                connect_saved_count,
            )

        except Exception as e:
            logger.error(
                "[VoicePointCalculator] process_vc_closed(vc_id=%s) error: %s",
                str(vc_id),
                e,
                exc_info=True,
            )

    # ─────────────────────────
    # calc
    # ─────────────────────────

    def calc_unmuted_time_per_user(
        self,
        *,
        events_per_user: Dict[str, List[Dict[str, Any]]],
        deleted_at: datetime,
        include_mic_mute: bool,
        include_speaker_mute: bool,
    ) -> Dict[str, int]:
        """
        ユーザーごとの「ポイント対象時間[msec]」を計算する。
        """
        result: Dict[str, int] = {}

        for user_id, events in events_per_user.items():
            state = UserVoiceStateForCalc()

            for ev in events:
                ev_ts_raw = ev.get("ts")
                if ev_ts_raw is None:
                    continue

                ev_ts = self._to_jst(ev_ts_raw)
                if ev_ts > deleted_at:
                    break

                ev_type = ev.get("type")
                effective_mute = self._effective_mute_from_event(
                    ev,
                    include_mic_mute=include_mic_mute,
                    include_speaker_mute=include_speaker_mute,
                )

                if ev_type == "JOIN":
                    state.in_vc = True
                    state.muted = effective_mute
                    if not state.muted:
                        state.current_unmute_start = ev_ts

                elif ev_type == "LEAVE":
                    if state.in_vc and not state.muted and state.current_unmute_start:
                        delta = (ev_ts - state.current_unmute_start).total_seconds() * 1000
                        state.total_unmuted_msec += int(delta)
                        state.current_unmute_start = None

                    state.in_vc = False
                    state.muted = effective_mute

                elif ev_type == "MUTE_ON":
                    if state.in_vc and not state.muted and state.current_unmute_start:
                        delta = (ev_ts - state.current_unmute_start).total_seconds() * 1000
                        state.total_unmuted_msec += int(delta)
                        state.current_unmute_start = None

                    state.muted = True

                elif ev_type == "MUTE_OFF":
                    state.muted = False
                    if state.in_vc:
                        state.current_unmute_start = ev_ts

            if state.in_vc and not state.muted and state.current_unmute_start:
                if deleted_at > state.current_unmute_start:
                    delta = (deleted_at - state.current_unmute_start).total_seconds() * 1000
                    state.total_unmuted_msec += int(delta)

            result[user_id] = state.total_unmuted_msec

        return result

    def calc_users_at_minutes(
        self,
        *,
        events_per_user: Dict[str, List[Dict[str, Any]]],
        created_at: datetime,
        deleted_at: datetime,
        minutes: int,
    ) -> int:
        """
        VC作成時刻から minutes 分後の時点で在室していた人数を返す。
        """
        target_time = created_at + timedelta(minutes=minutes)
        if deleted_at <= target_time:
            return 0

        count = 0

        for events in events_per_user.values():
            in_vc = False
            current_join: Optional[datetime] = None
            present_at_target = False

            for ev in events:
                ev_ts_raw = ev.get("ts")
                if ev_ts_raw is None:
                    continue

                ev_ts = self._to_jst(ev_ts_raw)
                ev_type = ev.get("type")

                if ev_type == "JOIN":
                    in_vc = True
                    current_join = ev_ts

                elif ev_type == "LEAVE":
                    if in_vc and current_join is not None and current_join <= target_time < ev_ts:
                        present_at_target = True
                        break

                    in_vc = False
                    current_join = None

            if not present_at_target and in_vc and current_join is not None:
                if current_join <= target_time < deleted_at:
                    present_at_target = True

            if present_at_target:
                count += 1

        return count

    def calc_points(
        self,
        *,
        unmuted_msec_per_user: Dict[str, int],
        num_users_at_threshold: int,
        owner_user_id: Optional[str],
        rule: VC_Point_Rule,
    ) -> Tuple[int, Dict[str, int]]:
        """
        ポイント計算本体。
        """
        connect_points_per_user: Dict[str, int] = {}

        for user_id, msec in unmuted_msec_per_user.items():
            minutes = msec // 60000

            if rule.limit_minutes is not None:
                minutes = min(minutes, int(rule.limit_minutes))

            blocks = minutes // int(rule.connect_block_minutes)
            points = int(blocks * int(rule.connect_point))
            connect_points_per_user[user_id] = points

        owner_points = 0
        if (
            owner_user_id is not None
            and rule.owner_bonus_point is not None
            and rule.owner_bonus_point > 0
            and rule.owner_threshold_min is not None
            and rule.owner_threshold_min > 0
        ):
            if num_users_at_threshold > 0:
                owner_points = int(num_users_at_threshold * int(rule.owner_bonus_point))

        return owner_points, connect_points_per_user

    # ─────────────────────────
    # save helpers
    # ─────────────────────────

    async def _save_owner_points(
        self,
        *,
        vc_id_str: str,
        owner_user_id: Optional[str],
        owner_event_type: Optional[Points_Type],
        owner_points: int,
        num_users_at_threshold: int,
        rule: VC_Point_Rule,
        ts_awarded: datetime,
        category_id: Optional[int],
        vc_type_value: str,
        base_note: str,
    ) -> bool:
        if owner_event_type is None or not owner_user_id:
            return False

        threshold = int(rule.owner_threshold_min or 0)

        if num_users_at_threshold <= 0:
            owner_points = 0

        if owner_points <= 0:
            return False

        note = f"{base_note} users_at_{threshold}min={num_users_at_threshold}"

        await self.fs_points.record_event(
            user_id=owner_user_id,
            event_type=owner_event_type,
            genre=Genre_Type.VC,
            delta=int(owner_points),
            ts=ts_awarded,
            note=note,
            source={"vc_id": vc_id_str, "category_id": category_id},
            meta={
                "vc_type": vc_type_value,
                "owner_threshold_min": threshold,
                "users_at_threshold": num_users_at_threshold,
                "owner_bonus_point": rule.owner_bonus_point,
            },
            nonce=vc_id_str,
        )
        return True

    async def _save_connect_points(
        self,
        *,
        vc_id_str: str,
        connect_points_per_user: Dict[str, int],
        connect_event_type: Points_Type,
        rule: VC_Point_Rule,
        ts_awarded: datetime,
        category_id: Optional[int],
        vc_type_value: str,
        base_note: str,
    ) -> int:
        saved_count = 0

        for user_id, pt in connect_points_per_user.items():
            if pt <= 0:
                continue

            await self.fs_points.record_event(
                user_id=str(user_id),
                event_type=connect_event_type,
                genre=Genre_Type.VC,
                delta=int(pt),
                ts=ts_awarded,
                note=base_note,
                source={"vc_id": vc_id_str, "category_id": category_id},
                meta={
                    "vc_type": vc_type_value,
                    "connect_block_minutes": int(rule.connect_block_minutes),
                    "connect_point": int(rule.connect_point),
                    "limit_minutes": (
                        int(rule.limit_minutes)
                        if rule.limit_minutes is not None
                        else None
                    ),
                    "include_mic_mute": bool(rule.include_mic_mute),
                    "include_speaker_mute": bool(rule.include_speaker_mute),
                },
                nonce=vc_id_str,
            )
            saved_count += 1

        return saved_count

    # ─────────────────────────
    # data helpers
    # ─────────────────────────

    @staticmethod
    def _build_events_per_user(
        members: Dict[str, Any],
    ) -> Dict[str, List[Dict[str, Any]]]:
        events_per_user: Dict[str, List[Dict[str, Any]]] = {}

        for user_id, member_data in members.items():
            events = (member_data or {}).get("events") or []
            normalized_events = sorted(
                [event for event in events if isinstance(event, dict)],
                key=lambda event: (event.get("ts") is None, event.get("ts")),
            )
            events_per_user[str(user_id)] = normalized_events

        return events_per_user

    @staticmethod
    def _effective_mute_from_event(
        ev: Dict[str, Any],
        *,
        include_mic_mute: bool,
        include_speaker_mute: bool,
    ) -> bool:
        """
        「ポイント対象外のミュート状態」なら True を返す。
        """
        mic_muted = bool(ev.get("is_self_mute") or ev.get("is_server_mute"))
        speaker_muted = bool(ev.get("is_self_deaf") or ev.get("is_server_deaf"))

        if include_mic_mute:
            mic_muted = False
        if include_speaker_mute:
            speaker_muted = False

        return bool(mic_muted or speaker_muted)

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _to_jst(ts: DateTimeLike) -> datetime:
        """
        Firestore Timestamp / datetime を JST timezone 付き datetime に正規化する。
        naive の場合は JST とみなす。
        """
        if isinstance(ts, DatetimeWithNanoseconds):
            return datetime.fromtimestamp(ts.timestamp(), TZ_JST)

        if ts.tzinfo is None:
            return ts.replace(tzinfo=TZ_JST)

        return ts.astimezone(TZ_JST)