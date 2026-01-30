# voice_point_calculator.py
# ✅ VC_POINT_RULES の include_mic_mute / include_speaker_mute に従って
#    「ミュート扱い（=ポイント対象外）」の判定を動的に切り替える版
# ✅ Points_Type / Genre_Type を使ってイベント別に FS_Points.record_event へ保存
# ✅ category_id は VC_LOG トップ（vc_doc["category_id"]）から参照する前提
# ✅ NEW: owner_threshold_min 時点の在室人数が 0 の場合 owner を計上しない（record_eventしない）
# ✅ NEW: connect_block_minutes を満たすメンバーが 0 の場合 connect を計上しない（record_eventが0件になる）

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from zoneinfo import ZoneInfo
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from assets.lists.points_list import VC_Point_Rule, VCType, VC_POINT_RULES
from firestores.fs_voice_log import FS_Voice_Log
from firestores.fs_points import FS_Points
from utils.enum import Points_Type, Genre_Type

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateTimeLike = Union[datetime, DatetimeWithNanoseconds]

TZ_JST = ZoneInfo("Asia/Tokyo")


def resolve_vc_type_from_category(category_id: Optional[int]) -> Optional[VCType]:
    """
    category_id から VCType を解決する。
    VC_POINT_RULES 側の category_ids に入っていないカテゴリは None。
    """
    if category_id is None:
        return None

    for vc_type, rule in VC_POINT_RULES.items():
        if category_id in (rule.category_ids or ()):
            return vc_type

    return None


def resolve_points_type_for_connect(vc_type: VCType) -> Points_Type:
    """
    VCType -> 接続ポイントのイベント型へ変換
    """
    if vc_type == VCType.NORMAL:
        return Points_Type.NORMAL_VC_CONNECT
    if vc_type == VCType.PUBLIC_ROOM:
        return Points_Type.PUBLIC_VC_CONNECT
    if vc_type == VCType.SECRET_ROOM:
        # ここは要件次第：secret_room を public と同じ扱いにするなら PUBLIC_VC_CONNECT に寄せる、なども可
        return Points_Type.PUBLIC_VC_CONNECT
    raise ValueError(f"Unhandled VCType for connect event: {vc_type}")


def resolve_points_type_for_owner(vc_type: VCType) -> Points_Type:
    """
    VCType -> オーナーボーナスのイベント型へ変換
    """
    if vc_type == VCType.NORMAL:
        return Points_Type.NORMAL_VC_OWNER
    if vc_type == VCType.PUBLIC_ROOM:
        return Points_Type.PUBLIC_VC_OWNER
    if vc_type == VCType.SECRET_ROOM:
        return Points_Type.PUBLIC_VC_OWNER
    raise ValueError(f"Unhandled VCType for owner event: {vc_type}")


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

    重要:
    - category_id は VC_LOG/{vc_id} トップに保存されている前提
    - ミュート判定は rule.include_mic_mute / rule.include_speaker_mute で動的に切替

    理想ルール:
    - owner_threshold_min 時点の在室人数が 0 の場合、owner_bonus_point は計上しない（保存しない）
    - connect_block_minutes を満たすメンバーが 0 の場合、connect も通常計上しない（保存0件）
    - ただし points_calculated は必ず立てる（再計算防止）
    """

    def __init__(self, fs_voice_log: Optional[FS_Voice_Log] = None, fs_points: Optional[FS_Points] = None):
        self.fs_voice_log = fs_voice_log or FS_Voice_Log()
        self.fs_points = fs_points or FS_Points()
        self.tz = TZ_JST

    # ─────────────────────────
    # public: VC削除時のエントリーポイント
    # ─────────────────────────

    async def process_vc_closed(self, vc_id: IntStr) -> None:
        """
        VC削除時に呼び出される想定のメイン処理。

        流れ:
        1) points_calculated をチェックして二重計算を防ぐ
        2) VC_LOG から vc_doc / members(events) を取得
        3) category_id -> vc_type -> rule を解決
        4) ユーザーごとの非ミュート時間を計算（ルールに従う）
        5) owner threshold 時点の人数を必要なら計算
        6) ルールに従って owner/connect のポイント算出
        7) FS_Points.record_event でイベント別に保存（0点は保存しない）
        8) VC_LOG に points_calculated を立てる
        """
        vc_id_str = str(vc_id)

        try:
            # すでに計算済みならスキップ
            if await self.fs_voice_log.is_points_calculated(vc_id_str):
                logger.info("[VoicePointCalculator] VC %s already points_calculated, skip.", vc_id_str)
                return

            # VC doc + members/events をまとめて取得
            payload = await self.fs_voice_log.fetch_vc_all(vc_id_str, include_event_doc_id=False)
            vc_doc = payload.get("vc") or {}
            members = payload.get("members") or {}

            if not vc_doc:
                logger.warning("[VoicePointCalculator] VC doc not found for vc_id=%s.", vc_id_str)
                return

            created_at_raw = vc_doc.get("created_at")
            deleted_at_raw = vc_doc.get("deleted_at")
            owner_user_id = vc_doc.get("owner_user_id")

            # ✅ VC_LOG に保存されている category_id を参照
            category_id_raw = vc_doc.get("category_id")
            category_id: Optional[int] = None
            if category_id_raw is not None:
                try:
                    category_id = int(category_id_raw)
                except Exception:
                    category_id = None

            vc_type = resolve_vc_type_from_category(category_id)
            if vc_type is None:
                logger.warning(
                    "[VoicePointCalculator] vc=%s category_id=%s => vc_type unresolved. skip.",
                    vc_id_str,
                    category_id,
                )
                return

            rule: VC_Point_Rule = VC_POINT_RULES[vc_type]

            # deleted_at が無い場合は「今」とみなす（保険）
            deleted_at = self._to_jst(deleted_at_raw) if deleted_at_raw is not None else datetime.now(self.tz)
            created_at: Optional[datetime] = self._to_jst(created_at_raw) if created_at_raw is not None else None

            # events_per_user 形式へ正規化
            events_per_user: Dict[str, List[Dict[str, Any]]] = {}
            for user_id, m in members.items():
                evs = (m or {}).get("events") or []
                evs = sorted(
                    [e for e in evs if isinstance(e, dict)],
                    key=lambda x: (x.get("ts") is None, x.get("ts")),
                )
                events_per_user[str(user_id)] = evs

            # ✅ ルールに従って非ミュート時間（msec）を計算
            unmuted_msec_per_user = self.calc_unmuted_time_per_user(
                events_per_user=events_per_user,
                deleted_at=deleted_at,
                include_mic_mute=bool(getattr(rule, "include_mic_mute", True)),
                include_speaker_mute=bool(getattr(rule, "include_speaker_mute", True)),
            )

            # owner bonus 判定用：threshold 分時点の在室人数
            num_users_at_threshold = 0
            if created_at is not None and rule.has_owner_bonus():
                num_users_at_threshold = self.calc_users_at_minutes(
                    events_per_user=events_per_user,
                    created_at=created_at,
                    deleted_at=deleted_at,
                    minutes=int(rule.owner_threshold_min or 0),
                )

            # ポイント計算（rule 注入）
            owner_points, connect_points_per_user = self.calc_points(
                unmuted_msec_per_user=unmuted_msec_per_user,
                num_users_at_threshold=num_users_at_threshold,
                owner_user_id=str(owner_user_id) if owner_user_id else None,
                rule=rule,
            )

            # 付与時刻（VC削除時刻を採用）
            ts_awarded = datetime.fromtimestamp(deleted_at.timestamp(), tz=self.tz)

            vc_type_value = getattr(vc_type, "value", str(vc_type))
            base_note = f"vc_type={vc_type_value} category_id={category_id}"

            # ✅ 保存するイベント種別を決める
            connect_event_type = resolve_points_type_for_connect(vc_type)

            owner_event_type: Optional[Points_Type] = None
            if rule.has_owner_bonus():
                owner_event_type = resolve_points_type_for_owner(vc_type)

            # ─────────────────────────
            # ✅ owner bonus 保存（理想ルール適用）
            # - threshold時点人数が0なら保存しない
            # ─────────────────────────
            owner_saved = False
            if owner_event_type is not None and owner_user_id:
                threshold = int(rule.owner_threshold_min or 0)

                # 理想: thresholdを満たす在室人数が0なら ownerは計上しない
                if num_users_at_threshold <= 0:
                    owner_points = 0

                if owner_points > 0:
                    note = f"{base_note} users_at_{threshold}min={num_users_at_threshold}"

                    await self.fs_points.record_event(
                        user_id=str(owner_user_id),
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
                        nonce=vc_id_str,  # 同一VCでの再実行に強くする
                    )
                    owner_saved = True

            # ─────────────────────────
            # ✅ connect 保存（理想ルール適用）
            # - connect_block_minutesを満たす(=pt>0になる)メンバーが0なら保存0件
            # ─────────────────────────
            connect_saved_count = 0

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
                        "limit_minutes": int(rule.limit_minutes) if rule.limit_minutes is not None else None,
                        "include_mic_mute": bool(getattr(rule, "include_mic_mute", True)),
                        "include_speaker_mute": bool(getattr(rule, "include_speaker_mute", True)),
                    },
                    nonce=vc_id_str,
                )
                connect_saved_count += 1

            # ✅ 理想: “満たすメンバーが0なら通常計上もしない”
            # → ここでは record_event が 0 件になるだけ（VC_LOG は計算済みにする）
            if connect_saved_count == 0:
                logger.info(
                    "[VoicePointCalculator] VC %s connect: no eligible members (block unmet). skip all connect awards.",
                    vc_id_str,
                )

            if not owner_saved and owner_event_type is not None and owner_user_id and num_users_at_threshold <= 0:
                logger.info(
                    "[VoicePointCalculator] VC %s owner: users_at_threshold=0, owner bonus skipped.",
                    vc_id_str,
                )

            # ✅ 計算済みフラグ（0点でも必ず立てる）
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
    # 時間計算系
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
        ユーザーごとの「ポイント対象となる合計時間[msec]」を計算する。

        include_mic_mute:
          True なら マイクミュートでもカウント
          False なら マイクミュート中の時間は除外（ポイント対象外）

        include_speaker_mute:
          True なら deaf でもカウント
          False なら スピーカーミュート(deaf)中の時間は除外
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

                else:
                    continue

            # 退室イベントが無いままVC終了した場合
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
        VC作成時刻 created_at から minutes 分後の時刻 T に在室していた人数。
        """
        T = created_at + timedelta(minutes=minutes)
        if deleted_at <= T:
            return 0

        count = 0

        for _, events in events_per_user.items():
            in_vc = False
            current_join: Optional[datetime] = None
            present_at_T = False

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
                    if in_vc and current_join is not None:
                        if current_join <= T < ev_ts:
                            present_at_T = True
                            break
                    in_vc = False
                    current_join = None

            # LEAVE が無いままVC終了しているケース
            if not present_at_T and in_vc and current_join is not None:
                if current_join <= T < deleted_at:
                    present_at_T = True

            if present_at_T:
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
        ポイント計算（VC_Point_Rule 注入版）

        ここでは points=0 も辞書には入れる（ログ・デバッグ用）。
        実際の保存は process_vc_closed 側で pt>0 のみ record_event する。
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
            # 理想: num_users_at_threshold が 0 なら owner_points=0（保存もしない）
            if num_users_at_threshold > 0:
                owner_points = int(num_users_at_threshold * int(rule.owner_bonus_point))
            else:
                owner_points = 0

        return owner_points, connect_points_per_user

    # ─────────────────────────
    # mute policy helper
    # ─────────────────────────

    @staticmethod
    def _effective_mute_from_event(
        ev: Dict[str, Any],
        *,
        include_mic_mute: bool,
        include_speaker_mute: bool,
    ) -> bool:
        """
        「ミュート扱い」なら True を返す（=ポイント対象外）。

        - mic_muted: self_mute or server_mute
        - speaker_muted: self_deaf or server_deaf

        include_* が True の場合、そのミュート要因は「ミュート扱いにしない」。
        """
        mic_muted = bool(ev.get("is_self_mute") or ev.get("is_server_mute"))
        speaker_muted = bool(ev.get("is_self_deaf") or ev.get("is_server_deaf"))

        # 含める設定なら、ミュート扱いにしない
        if include_mic_mute:
            mic_muted = False
        if include_speaker_mute:
            speaker_muted = False

        return bool(mic_muted or speaker_muted)

    # ─────────────────────────
    # small helpers
    # ─────────────────────────

    @staticmethod
    def _to_jst(ts: DateTimeLike) -> datetime:
        """
        Firestore Timestamp / datetime を JST timezone 付き datetime に正規化。
        naive の場合は JST とみなす。
        """
        if isinstance(ts, DatetimeWithNanoseconds):
            return datetime.fromtimestamp(ts.timestamp(), TZ_JST)

        if ts.tzinfo is None:
            return ts.replace(tzinfo=TZ_JST)

        return ts.astimezone(TZ_JST)
