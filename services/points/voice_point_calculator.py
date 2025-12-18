# voice_point_calculator.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, Tuple

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.api_core.datetime_helpers import DatetimeWithNanoseconds

# パスはあなたの構成に合わせてください
from firestores.fs_voice_log import FS_Voice_Log
from firestores.fs_points import FS_Points

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateTimeLike = Union[datetime, DatetimeWithNanoseconds]

TZ_JST = ZoneInfo("Asia/Tokyo")

# ───────── ポイント設定（あとで調整しやすいように定数化） ─────────

# 部屋主ボーナス: VC開始から何分後の人数を見るか
OWNER_BONUS_THRESHOLD_MINUTES = 10

# 部屋主ボーナス: しきい値到達時の在室ユーザー1人あたりのポイント
OWNER_BONUS_POINT_PER_USER = 25

# 接続時間ポイント: 何分ごとに1ブロックとするか
CONNECT_BLOCK_MINUTES = 15

# 接続時間ポイント: 1ブロックあたりのポイント
CONNECT_POINT_PER_BLOCK = 10


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
    """

    def __init__(self, fs_voice_log: FS_Voice_Log, fs_points: FS_Points):
        self.fs_voice_log = fs_voice_log
        self.fs_points = fs_points
        self.tz = TZ_JST

    # ─────────────────────────
    # public: VC削除時のエントリーポイント
    # ─────────────────────────

    async def process_vc_closed(self, vc_id: IntStr) -> None:
        """
        VC削除時に呼び出される想定のメイン処理。

        フロー:
        - 既に points_calculated なら何もしない
        - VC_LOG/{vc_id}.meta から created_at / deleted_at / owner_user_id を取得
        - 全メンバーのイベントを取得
        - ユーザーごとの「ミュートしてない時間」を算出
        - OWNER_BONUS_THRESHOLD_MINUTES 分後時点の在室人数を算出
        - ポイント計算
        - FS_Points でポイントを書き込み
        - FS_Voice_Log で points_calculated フラグを立てる
        """
        vc_id_str = str(vc_id)

        try:
            # すでに計算済みならスキップ
            if await self.fs_voice_log.is_points_calculated(vc_id_str):
                logger.info(f"[VoicePointCalculator] VC {vc_id_str} already points_calculated, skip.")
                return

            # meta 取得
            meta = await self.fs_voice_log.get_vc_meta(vc_id_str)
            if not meta:
                logger.warning(f"[VoicePointCalculator] VC meta not found for vc_id={vc_id_str}.")
                return

            created_at_raw = meta.get("created_at")  # Firestore Timestamp or None
            deleted_at_raw = meta.get("deleted_at")  # Firestore Timestamp or None
            owner_user_id = meta.get("owner_user_id")  # str or None

            logger.info(
                "[VoicePointCalculator] meta for vc=%s "
                "created_at=%s deleted_at=%s owner_user_id=%s",
                vc_id_str, created_at_raw, deleted_at_raw, owner_user_id,
            )

            if deleted_at_raw is None:
                deleted_at = datetime.now(self.tz)
            else:
                deleted_at = self._to_jst(deleted_at_raw)

            created_at: Optional[datetime]
            if created_at_raw is None:
                created_at = None
            else:
                created_at = self._to_jst(created_at_raw)

            # 全メンバーのイベント取得
            events_per_user = await self.fs_voice_log.fetch_all_member_events(vc_id_str)
            # { user_id: [ { "type": ..., "ts": ..., ... }, ... ], ... }

            # ★ デバッグログ追加: どの user_id のイベントが取れているか
            logger.info(
                "[VoicePointCalculator] vc=%s events_per_user_keys=%s",
                vc_id_str, list(events_per_user.keys()),
            )

            # ミュートじゃない合計時間
            unmuted_msec_per_user = self.calc_unmuted_time_per_user(
                events_per_user=events_per_user,
                deleted_at=deleted_at,
            )

            # ★ デバッグログ追加: 各ユーザーのアンミュート時間
            logger.info(
                "[VoicePointCalculator] vc=%s unmuted_msec_per_user=%s",
                vc_id_str, unmuted_msec_per_user,
            )

            # OWNER_BONUS_THRESHOLD_MINUTES 分後の在室人数
            num_users_at_10min = 0
            if created_at is not None:
                num_users_at_10min = self.calc_users_at_10min(
                    events_per_user=events_per_user,
                    created_at=created_at,
                    deleted_at=deleted_at,
                )

            logger.info(
                "[VoicePointCalculator] vc=%s num_users_at_%dmin=%d",
                vc_id_str, OWNER_BONUS_THRESHOLD_MINUTES, num_users_at_10min,
            )

            # ポイント計算
            owner_points, connect_points_per_user = self.calc_points(
                unmuted_msec_per_user=unmuted_msec_per_user,
                num_users_at_10min=num_users_at_10min,
                owner_user_id=owner_user_id,
            )

            logger.info(
                "[VoicePointCalculator] vc=%s connect_points_per_user=%s",
                vc_id_str, connect_points_per_user,
            )

            ts_awarded = datetime.fromtimestamp(deleted_at.timestamp(), tz=self.tz)

            # 部屋主ボーナス
            if owner_user_id and owner_points > 0:
                await self.fs_points.add_owner_points(
                    user_id=owner_user_id,
                    vc_id=vc_id_str,
                    ts_awarded=ts_awarded,
                    point=owner_points,
                    note=f"users_at_{OWNER_BONUS_THRESHOLD_MINUTES}min={num_users_at_10min}",
                )

            # 接続時間ポイント（全員分）
            for user_id, pt in connect_points_per_user.items():
                if pt <= 0:
                    continue
                await self.fs_points.add_connect_points(
                    user_id=user_id,
                    vc_id=vc_id_str,
                    ts_awarded=ts_awarded,
                    point=pt,
                    note=None,
                )

            # 計算済みフラグ
            await self.fs_voice_log.mark_points_calculated(vc_id_str, ts_awarded)

            logger.info(
                f"[VoicePointCalculator] Processed VC {vc_id_str}: "
                f"owner={owner_user_id}, owner_points={owner_points}, "
                f"users={len(connect_points_per_user)}"
            )

        except Exception as e:
            logger.error(f"[VoicePointCalculator] process_vc_closed(vc_id={vc_id_str}) error: {e}", exc_info=True)

    # ─────────────────────────
    # 時間計算系
    # ─────────────────────────

    def calc_unmuted_time_per_user(
        self,
        *,
        events_per_user: Dict[str, List[Dict[str, Any]]],
        deleted_at: datetime,
    ) -> Dict[str, int]:
        """
        ユーザーごとの「ミュートじゃない状態の合計時間[msec]」を計算する。

        - イベントは FS_Voice_Log 側で ts 昇順に並んでいる前提。
        - deleted_at 以降はカウントしない。
        """
        result: Dict[str, int] = {}

        for user_id, events in events_per_user.items():
            state = UserVoiceStateForCalc()

            for ev in events:
                ev_ts_raw = ev.get("ts")
                if ev_ts_raw is None:
                    continue
                ev_ts = self._to_jst(ev_ts_raw)

                # VC削除時を超えたイベントは無視
                if ev_ts > deleted_at:
                    break

                ev_type = ev.get("type")
                effective_mute = self._effective_mute_from_event(ev)

                if ev_type == "JOIN":
                    # JOIN は「新しいセッション開始」とみなす
                    state.in_vc = True
                    state.muted = effective_mute
                    # ミュートされていないならここから unmute 区間開始
                    if not state.muted:
                        state.current_unmute_start = ev_ts

                elif ev_type == "LEAVE":
                    # LEAVE で、unmute 区間が続いていたらここで締める
                    if state.in_vc and not state.muted and state.current_unmute_start:
                        delta = (ev_ts - state.current_unmute_start).total_seconds() * 1000
                        state.total_unmuted_msec += int(delta)
                        state.current_unmute_start = None

                    state.in_vc = False
                    state.muted = effective_mute  # 一応同期

                elif ev_type == "MUTE_ON":
                    # 直前まで unmute だったなら、その区間を締める
                    if state.in_vc and not state.muted and state.current_unmute_start:
                        delta = (ev_ts - state.current_unmute_start).total_seconds() * 1000
                        state.total_unmuted_msec += int(delta)
                        state.current_unmute_start = None

                    state.muted = True

                elif ev_type == "MUTE_OFF":
                    state.muted = False
                    # VC 内にいて、ここから unmute 区間を開始
                    if state.in_vc:
                        state.current_unmute_start = ev_ts

                else:
                    # 想定外の type は無視
                    continue

            # イベントを全部見たあと、
            # まだ unmute 区間が続いていれば deleted_at までを加算
            if state.in_vc and not state.muted and state.current_unmute_start:
                end_ts = deleted_at
                if end_ts > state.current_unmute_start:
                    delta = (end_ts - state.current_unmute_start).total_seconds() * 1000
                    state.total_unmuted_msec += int(delta)

            result[user_id] = state.total_unmuted_msec

        return result

    def calc_users_at_10min(
        self,
        *,
        events_per_user: Dict[str, List[Dict[str, Any]]],
        created_at: datetime,
        deleted_at: datetime,
    ) -> int:
        """
        VC作成時刻 created_at から OWNER_BONUS_THRESHOLD_MINUTES 分後の時刻 T に、
        その VC に在室していたユーザー数を求める。
        """
        T = created_at + timedelta(minutes=OWNER_BONUS_THRESHOLD_MINUTES)

        # VC がそれ以前に削除されていたら、ボーナス条件は満たさないとみなして 0
        if deleted_at <= T:
            return 0

        count = 0

        for user_id, events in events_per_user.items():
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
                        # 区間 [current_join, ev_ts) に T が含まれるか
                        if current_join <= T < ev_ts:
                            present_at_T = True
                            break
                    in_vc = False
                    current_join = None

                # MUTE_ON / MUTE_OFF は在室判定には関係ないので無視

            # イベント列が終わった後も in_vc==True で current_join が残っているなら、
            # セッションは [current_join, deleted_at) とみなす。
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
        num_users_at_10min: int,
        owner_user_id: Optional[str],
    ) -> Tuple[int, Dict[str, int]]:
        """
        ポイント計算を行う。

        - 接続時間ポイント (VC_Connect):
            total_unmuted_min = floor(msec / 60000)
            blocks = floor(total_unmuted_min / CONNECT_BLOCK_MINUTES)
            connect_points = blocks * CONNECT_POINT_PER_BLOCK

        - 部屋主ボーナス (VC_Owner):
            owner_points = num_users_at_10min * OWNER_BONUS_POINT_PER_USER
        """
        connect_points_per_user: Dict[str, int] = {}

        for user_id, msec in unmuted_msec_per_user.items():
            minutes = msec // 60000
            blocks = minutes // CONNECT_BLOCK_MINUTES
            points = int(blocks * CONNECT_POINT_PER_BLOCK)
            connect_points_per_user[user_id] = points

        owner_points = 0
        if owner_user_id is not None:
            owner_points = num_users_at_10min * OWNER_BONUS_POINT_PER_USER

        return owner_points, connect_points_per_user

    # ─────────────────────────
    # 小ヘルパー
    # ─────────────────────────

    @staticmethod
    def _to_jst(ts: DateTimeLike) -> datetime:
        """
        Firestore Timestamp / datetime を JST timezone 付き datetime に正規化。
        naive の場合は JST とみなす。
        """
        if isinstance(ts, DatetimeWithNanoseconds):
            # timestamp() から「普通の datetime」に作り直すのが一番安全
            return datetime.fromtimestamp(ts.timestamp(), TZ_JST)

        if ts.tzinfo is None:
            return ts.replace(tzinfo=TZ_JST)

        return ts.astimezone(TZ_JST)

    @staticmethod
    def _effective_mute_from_event(ev: Dict[str, Any]) -> bool:
        """
        イベント dict から「ミュート扱いか」を判定する。
        """
        return bool(
            ev.get("is_self_mute")
            or ev.get("is_self_deaf")
            or ev.get("is_server_mute")
            or ev.get("is_server_deaf")
        )
