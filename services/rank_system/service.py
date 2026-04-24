# services/rank/service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal

import time

from .level_math import RankProgress, progress_from_points


RankKind = Literal["tc", "vc"]


@dataclass(frozen=True)
class RankState:
    """永続化する想定のユーザーランク状態（最小構成）。"""
    guild_id: int
    user_id: int

    tc_points: int
    vc_points: int

    updated_at: float  # unix seconds


class RankRepository:
    """
    永続化の抽象I/F。
    Firestore実装は repo_firestore.py でこのI/Fを満たすクラスにする想定。
    """

    async def get_state(self, guild_id: int, user_id: int) -> Optional[RankState]:
        raise NotImplementedError

    async def upsert_state(self, state: RankState) -> None:
        raise NotImplementedError

    async def add_points(
        self,
        guild_id: int,
        user_id: int,
        *,
        add_tc: int = 0,
        add_vc: int = 0,
        now: Optional[float] = None,
    ) -> RankState:
        """
        競合しにくい形で加算したいので、repo側でtransaction/atomic incrementにするのが理想。
        仮実装では get→加算→upsert でもOK。
        """
        raise NotImplementedError


class InMemoryRankRepository(RankRepository):
    """
    まず動かす用（再起動で消える）。
    guild_id, user_id ごとの RankState を保持。
    """

    def __init__(self) -> None:
        self._data: dict[tuple[int, int], RankState] = {}

    async def get_state(self, guild_id: int, user_id: int) -> Optional[RankState]:
        return self._data.get((guild_id, user_id))

    async def upsert_state(self, state: RankState) -> None:
        self._data[(state.guild_id, state.user_id)] = state

    async def add_points(
        self,
        guild_id: int,
        user_id: int,
        *,
        add_tc: int = 0,
        add_vc: int = 0,
        now: Optional[float] = None,
    ) -> RankState:
        now = time.time() if now is None else float(now)

        cur = self._data.get((guild_id, user_id))
        if cur is None:
            cur = RankState(
                guild_id=guild_id,
                user_id=user_id,
                tc_points=0,
                vc_points=0,
                updated_at=now,
            )

        tc = max(0, cur.tc_points + int(add_tc))
        vc = max(0, cur.vc_points + int(add_vc))

        new_state = RankState(
            guild_id=guild_id,
            user_id=user_id,
            tc_points=tc,
            vc_points=vc,
            updated_at=now,
        )
        self._data[(guild_id, user_id)] = new_state
        return new_state


class CooldownStore:
    """
    TCなどで「ユーザーごとのクールダウン」を持ちたい場合の最小I/F。
    - Firestoreに持たずメモリでOKなら、このまま InMemoryCooldownStore を使う。
    """

    async def get_last_ts(self, key: str) -> Optional[float]:
        raise NotImplementedError

    async def set_last_ts(self, key: str, ts: float) -> None:
        raise NotImplementedError


class InMemoryCooldownStore(CooldownStore):
    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    async def get_last_ts(self, key: str) -> Optional[float]:
        return self._last.get(key)

    async def set_last_ts(self, key: str, ts: float) -> None:
        self._last[key] = ts


@dataclass(frozen=True)
class AddPointsResult:
    """points加算後に返す情報（embed表示用など）。"""
    state: RankState

    # 合算（TC+VC）
    total_points: int

    # 進捗（合算を元に算出）
    progress: RankProgress


class RankService:
    """
    extensions から呼ぶ “ユースケース” 層。
    - pointsを加算して永続化
    - 合算pointsから level_math で progress を返す
    """

    def __init__(
        self,
        repo: RankRepository,
        *,
        max_level: Optional[int] = 100,
        cooldown_store: Optional[CooldownStore] = None,
    ) -> None:
        self.repo = repo
        self.max_level = max_level
        self.cooldowns = cooldown_store or InMemoryCooldownStore()

    def _cooldown_key(self, guild_id: int, user_id: int, kind: RankKind) -> str:
        return f"rank:{guild_id}:{user_id}:{kind}"

    async def add_points(
        self,
        guild_id: int,
        user_id: int,
        *,
        tc_points: int = 0,
        vc_points: int = 0,
        now: Optional[float] = None,
    ) -> AddPointsResult:
        """
        純粋に加算して結果を返す（クールダウン判定なし）。
        """
        state = await self.repo.add_points(
            guild_id,
            user_id,
            add_tc=int(tc_points),
            add_vc=int(vc_points),
            now=now,
        )

        total = state.tc_points + state.vc_points
        pr = progress_from_points(total, max_level=self.max_level)

        return AddPointsResult(
            state=state,
            total_points=total,
            progress=pr,
        )

    async def add_points_with_cooldown(
        self,
        guild_id: int,
        user_id: int,
        *,
        kind: RankKind,
        add_points: int,
        cooldown_sec: float,
        now: Optional[float] = None,
    ) -> Optional[AddPointsResult]:
        """
        例: on_message のTC付与で使う想定。
        - kind="tc" に対して cooldown を適用
        - クールダウン中なら None を返す
        """
        now = time.time() if now is None else float(now)
        key = self._cooldown_key(guild_id, user_id, kind)
        last = await self.cooldowns.get_last_ts(key)

        if last is not None and (now - last) < float(cooldown_sec):
            return None

        await self.cooldowns.set_last_ts(key, now)

        if kind == "tc":
            return await self.add_points(guild_id, user_id, tc_points=add_points, now=now)
        else:
            return await self.add_points(guild_id, user_id, vc_points=add_points, now=now)

    async def get_progress(
        self,
        guild_id: int,
        user_id: int,
    ) -> AddPointsResult:
        """
        現在値だけ読み出して progress を返す（付与なし）。
        """
        st = await self.repo.get_state(guild_id, user_id)
        now = time.time()
        if st is None:
            st = RankState(guild_id=guild_id, user_id=user_id, tc_points=0, vc_points=0, updated_at=now)

        total = st.tc_points + st.vc_points
        pr = progress_from_points(total, max_level=self.max_level)

        return AddPointsResult(
            state=st,
            total_points=total,
            progress=pr,
        )
