from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

from firestores.fs_talk_history import FS_Talk_History

from .config import (
    CATEGORY_TALK_HISTORY_CONFIGS,
    DEFAULT_TALK_HISTORY_CONFIG,
)

logger = logging.getLogger(__name__)

PairKey = Tuple[int, int]  # (user1_id, user2_id)


@dataclass
class MemberState:
    vc_id: int
    user_id: int
    countable: bool
    joined_at: float
    last_changed_at: float


@dataclass
class PairSession:
    vc_id: int
    category_id: Optional[int]
    user1_id: int
    user2_id: int
    started_at: float
    last_resumed_at: Optional[float]
    accumulated_seconds: float = 0.0
    qualified_notified: bool = False

    @property
    def pair_key(self) -> PairKey:
        return (self.user1_id, self.user2_id)

    def add_until(self, now_ts: float) -> float:
        if self.last_resumed_at is None:
            return 0.0
        delta = max(0.0, float(now_ts) - float(self.last_resumed_at))
        if delta > 0:
            self.accumulated_seconds += delta
            self.last_resumed_at = now_ts
        return delta

    def pause(self, now_ts: float) -> float:
        if self.last_resumed_at is None:
            return 0.0
        delta = max(0.0, float(now_ts) - float(self.last_resumed_at))
        if delta > 0:
            self.accumulated_seconds += delta
        self.last_resumed_at = None
        return delta

    def resume(self, now_ts: float) -> None:
        self.last_resumed_at = float(now_ts)


@dataclass
class VoiceTrackerConfig:
    qualify_seconds: float = 300.0
    flush_seconds: float = 30.0
    recent_write_ttl: float = 15.0
    min_write_seconds: float = 1.0


class TalkHistoryTracker:
    def __init__(
        self,
        fs_talk_history: FS_Talk_History,
        *,
        config: Optional[VoiceTrackerConfig] = None,
    ):
        self.fs_talk_history = fs_talk_history
        self.config = config or VoiceTrackerConfig(
            qualify_seconds=float(getattr(fs_talk_history, "qualify_seconds", 300.0))
        )

        self._vc_members: Dict[int, Set[int]] = {}
        self._members: Dict[int, MemberState] = {}
        self._pairs: Dict[PairKey, PairSession] = {}
        self._recent_writes: Dict[PairKey, float] = {}

        self._lock = asyncio.Lock()

    def snapshot(self) -> dict:
        return {
            "vc_count": len(self._vc_members),
            "member_count": len(self._members),
            "pair_count": len(self._pairs),
        }

    async def on_join(
        self,
        *,
        vc_id: int,
        category_id: Optional[int],
        user_id: int,
        countable: bool,
        now_ts: Optional[float] = None,
    ) -> None:
        now = self._now(now_ts)
        vc_id = int(vc_id)
        user_id = int(user_id)
        category_id = int(category_id) if category_id is not None else None

        async with self._lock:
            old_state = self._members.get(user_id)
            if old_state is not None and int(old_state.vc_id) != vc_id:
                self._discard_member_from_vc(int(old_state.vc_id), user_id)

            self._ensure_vc_set(vc_id)

            state = MemberState(
                vc_id=vc_id,
                user_id=user_id,
                countable=bool(countable),
                joined_at=now,
                last_changed_at=now,
            )
            self._members[user_id] = state

            existing_members = list(self._vc_members[vc_id])
            self._vc_members[vc_id].add(user_id)

            for other_user_id in existing_members:
                other_user_id = int(other_user_id)

                if other_user_id == user_id:
                    continue

                other = self._members.get(other_user_id)
                if other is None:
                    continue
                if int(other.vc_id) != vc_id:
                    continue

                self._ensure_pair_session(
                    vc_id=vc_id,
                    category_id=category_id,
                    user1_id=user_id,
                    user2_id=other_user_id,
                    now_ts=now,
                    active=bool(countable and other.countable),
                )

            await self._flush_due_pairs_locked(now)

    async def on_leave(
        self,
        *,
        vc_id: int,
        user_id: int,
        now_ts: Optional[float] = None,
    ) -> None:
        now = self._now(now_ts)

        async with self._lock:
            state = self._members.get(int(user_id))
            if state is None:
                self._discard_member_from_vc(int(vc_id), int(user_id))
                return

            other_ids = list(self._vc_members.get(int(vc_id), set()))
            for other_user_id in other_ids:
                if int(other_user_id) == int(user_id):
                    continue
                await self._finalize_pair_with_user_locked(
                    user1_id=int(user_id),
                    user2_id=int(other_user_id),
                    now_ts=now,
                )

            self._discard_member_from_vc(int(vc_id), int(user_id))
            self._members.pop(int(user_id), None)

    async def on_state_change(
        self,
        *,
        vc_id: int,
        user_id: int,
        countable: bool,
        now_ts: Optional[float] = None,
    ) -> None:
        now = self._now(now_ts)

        async with self._lock:
            state = self._members.get(int(user_id))
            if state is None:
                return

            old_countable = bool(state.countable)
            new_countable = bool(countable)

            if old_countable == new_countable:
                return

            state.countable = new_countable
            state.last_changed_at = now

            other_ids = list(self._vc_members.get(int(vc_id), set()))
            for other_user_id in other_ids:
                if int(other_user_id) == int(user_id):
                    continue

                other = self._members.get(int(other_user_id))
                if other is None:
                    continue
                if int(other.vc_id) != int(vc_id):
                    continue

                key = self._pair_key(int(user_id), int(other_user_id))
                pair = self._pairs.get(key)

                if pair is None:
                    self._ensure_pair_session(
                        vc_id=int(vc_id),
                        category_id=None,
                        user1_id=int(user_id),
                        user2_id=int(other_user_id),
                        now_ts=now,
                        active=bool(new_countable and other.countable),
                    )
                    continue

                should_be_active = bool(new_countable and other.countable)

                if should_be_active:
                    if pair.last_resumed_at is None:
                        pair.resume(now)
                else:
                    pair.pause(now)
                    await self._flush_pair_if_needed_locked(pair, force=False, now_ts=now)

            await self._flush_due_pairs_locked(now)

    async def on_move(
        self,
        *,
        before_vc_id: Optional[int],
        after_vc_id: Optional[int],
        after_category_id: Optional[int],
        user_id: int,
        after_countable: bool,
        now_ts: Optional[float] = None,
    ) -> None:
        now = self._now(now_ts)

        if before_vc_id is not None:
            await self.on_leave(
                vc_id=int(before_vc_id),
                user_id=int(user_id),
                now_ts=now,
            )

        if after_vc_id is not None:
            await self.on_join(
                vc_id=int(after_vc_id),
                category_id=int(after_category_id) if after_category_id is not None else None,
                user_id=int(user_id),
                countable=bool(after_countable),
                now_ts=now,
            )

    async def flush_all(self) -> None:
        now = self._now(None)

        async with self._lock:
            for pair in list(self._pairs.values()):
                pair.pause(now)
                await self._flush_pair_if_needed_locked(pair, force=True, now_ts=now)

            self._pairs.clear()

    async def flush_vc(self, *, vc_id: int, now_ts: Optional[float] = None) -> None:
        now = self._now(now_ts)

        async with self._lock:
            user_ids = list(self._vc_members.get(int(vc_id), set()))
            visited: Set[PairKey] = set()

            for user_id in user_ids:
                for other_user_id in user_ids:
                    if int(user_id) >= int(other_user_id):
                        continue
                    key = self._pair_key(int(user_id), int(other_user_id))
                    if key in visited:
                        continue
                    visited.add(key)

                    pair = self._pairs.get(key)
                    if pair is None:
                        continue

                    pair.pause(now)
                    await self._flush_pair_if_needed_locked(pair, force=True, now_ts=now)

            for user_id in user_ids:
                self._members.pop(int(user_id), None)
            self._vc_members.pop(int(vc_id), None)

            for key in list(self._pairs.keys()):
                pair = self._pairs.get(key)
                if pair is None:
                    continue
                if int(pair.vc_id) == int(vc_id):
                    self._pairs.pop(key, None)

    @staticmethod
    def _now(now_ts: Optional[float]) -> float:
        return float(now_ts if now_ts is not None else time.time())

    @staticmethod
    def _pair_users(user1_id: int, user2_id: int) -> Tuple[int, int]:
        a = int(user1_id)
        b = int(user2_id)

        if a == b:
            raise ValueError("user1_id and user2_id must be different")

        return (a, b) if a < b else (b, a)

    def _pair_key(self, user1_id: int, user2_id: int) -> PairKey:
        a, b = self._pair_users(user1_id, user2_id)
        return (int(a), int(b))

    def _ensure_vc_set(self, vc_id: int) -> None:
        if int(vc_id) not in self._vc_members:
            self._vc_members[int(vc_id)] = set()

    def _discard_member_from_vc(self, vc_id: int, user_id: int) -> None:
        s = self._vc_members.get(int(vc_id))
        if s is None:
            return
        s.discard(int(user_id))
        if not s:
            self._vc_members.pop(int(vc_id), None)

    def _resolve_qualify_seconds(self, category_id: Optional[int]) -> float:
        if category_id is not None:
            cfg = CATEGORY_TALK_HISTORY_CONFIGS.get(int(category_id))
            if cfg is not None:
                return float(cfg.qualify_seconds)
        return float(DEFAULT_TALK_HISTORY_CONFIG.qualify_seconds)

    def _ensure_pair_session(
        self,
        *,
        vc_id: int,
        category_id: Optional[int],
        user1_id: int,
        user2_id: int,
        now_ts: float,
        active: bool,
    ) -> Optional[PairSession]:
        if int(user1_id) == int(user2_id):
            logger.warning(
                "[TalkHistoryTracker] skip self pair ensure vc_id=%s user_id=%s",
                vc_id,
                user1_id,
            )
            return None

        key = self._pair_key(user1_id, user2_id)
        pair = self._pairs.get(key)
        if pair is not None:
            if active and pair.last_resumed_at is None:
                pair.resume(now_ts)
            elif not active and pair.last_resumed_at is not None:
                pair.pause(now_ts)

            if category_id is not None:
                pair.category_id = int(category_id)

            return pair

        a, b = self._pair_users(user1_id, user2_id)
        pair = PairSession(
            vc_id=int(vc_id),
            category_id=int(category_id) if category_id is not None else None,
            user1_id=int(a),
            user2_id=int(b),
            started_at=float(now_ts),
            last_resumed_at=float(now_ts) if active else None,
        )
        self._pairs[key] = pair
        return pair

    async def _finalize_pair_with_user_locked(
        self,
        *,
        user1_id: int,
        user2_id: int,
        now_ts: float,
    ) -> None:
        if int(user1_id) == int(user2_id):
            return

        key = self._pair_key(user1_id, user2_id)
        pair = self._pairs.get(key)
        if pair is None:
            return

        pair.pause(now_ts)
        await self._flush_pair_if_needed_locked(pair, force=True, now_ts=now_ts)
        self._pairs.pop(key, None)

    async def _flush_due_pairs_locked(self, now_ts: float) -> None:
        for pair in list(self._pairs.values()):
            if int(pair.user1_id) == int(pair.user2_id):
                logger.warning(
                    "[TalkHistoryTracker] remove invalid self pair vc_id=%s pair=%s_%s",
                    pair.vc_id,
                    pair.user1_id,
                    pair.user2_id,
                )
                self._pairs.pop(pair.pair_key, None)
                continue

            if pair.last_resumed_at is not None:
                live_delta = max(0.0, float(now_ts) - float(pair.last_resumed_at))
                pending = float(pair.accumulated_seconds) + live_delta
            else:
                pending = float(pair.accumulated_seconds)

            if pending >= float(self.config.flush_seconds):
                if pair.last_resumed_at is not None:
                    pair.add_until(now_ts)
                await self._flush_pair_if_needed_locked(pair, force=False, now_ts=now_ts)

    async def _flush_pair_if_needed_locked(
        self,
        pair: PairSession,
        *,
        force: bool,
        now_ts: float,
    ) -> None:
        if int(pair.user1_id) == int(pair.user2_id):
            logger.warning(
                "[TalkHistoryTracker] skip self pair flush vc_id=%s pair=%s_%s",
                pair.vc_id,
                pair.user1_id,
                pair.user2_id,
            )
            pair.accumulated_seconds = 0.0
            self._pairs.pop(pair.pair_key, None)
            return

        pending = float(pair.accumulated_seconds)

        if not force and pending < float(self.config.flush_seconds):
            return

        if pending < float(self.config.min_write_seconds):
            if force:
                pair.accumulated_seconds = 0.0
            return

        key = pair.pair_key
        last_write_ts = self._recent_writes.get(key, 0.0)

        if (not force) and (float(now_ts) - float(last_write_ts) < float(self.config.recent_write_ttl)):
            return

        qualify_seconds = self._resolve_qualify_seconds(pair.category_id)

        try:
            total = await self.fs_talk_history.add_shared_seconds(
                user1_id=int(pair.user1_id),
                user2_id=int(pair.user2_id),
                seconds=float(pending),
                auto_qualify=True,
                qualify_seconds=float(qualify_seconds),
                update_index=True,
            )
            pair.accumulated_seconds = 0.0
            self._recent_writes[key] = float(now_ts)

            if (not pair.qualified_notified) and float(total) >= float(qualify_seconds):
                pair.qualified_notified = True

        except Exception:
            logger.exception(
                "[TalkHistoryTracker] flush failed vc_id=%s pair=%s_%s pending=%.3f",
                pair.vc_id,
                pair.user1_id,
                pair.user2_id,
                pending,
            )

    async def prune_stale_recent_writes(self, *, now_ts: Optional[float] = None) -> None:
        now = self._now(now_ts)
        ttl = max(float(self.config.recent_write_ttl), 1.0)

        async with self._lock:
            for key, ts in list(self._recent_writes.items()):
                if float(now) - float(ts) >= ttl:
                    self._recent_writes.pop(key, None)

    async def remove_user_everywhere(self, *, user_id: int, now_ts: Optional[float] = None) -> None:
        now = self._now(now_ts)

        async with self._lock:
            state = self._members.get(int(user_id))
            if state is not None:
                vc_id = int(state.vc_id)
                other_ids = list(self._vc_members.get(vc_id, set()))

                for other_user_id in other_ids:
                    if int(other_user_id) == int(user_id):
                        continue
                    await self._finalize_pair_with_user_locked(
                        user1_id=int(user_id),
                        user2_id=int(other_user_id),
                        now_ts=now,
                    )

                self._discard_member_from_vc(vc_id, int(user_id))
                self._members.pop(int(user_id), None)