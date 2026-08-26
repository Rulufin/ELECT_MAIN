# services/rank/level_math.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Tuple, Optional, Literal


# =========================================================
# Level Math (ProBot-like, harder near Lv100)
# =========================================================
#
# points（累計） -> level を逆算し、
# 次レベルまでの必要points・進捗率も返す。
#
# モデル（単調増加）:
#   TotalPoints(L) = A * L^2 * (1 + B * (L/S)^4)
#
# text / voice で曲線パラメータを分離して、
# 後で調整しやすい形にしている。
# =========================================================


# -------------------------
# Curve Params
# -------------------------
@dataclass(frozen=True)
class CurveParams:
    """
    曲線パラメータ（調整ポイント）
    - A: 低Lvの伸び（Lv10近辺に強く影響）
    - B: 高Lvの重さ（後半に強く影響）
    - SCALE_LEVEL: 曲線の“基準レベル”（通常100固定がおすすめ）
    - default_max_level: 表示上限（Noneなら無制限）
    """
    A: float
    B: float = 0.36
    SCALE_LEVEL: float = 100.0
    default_max_level: Optional[int] = 100

DEFAULT_MAX_LEVEL: Final[Optional[int]] = 100

# ★ここだけ触ればOK（text / voice 個別）
TEXT_PARAMS: Final[CurveParams] = CurveParams(
    A=20,
    B=0.36,
    SCALE_LEVEL=100.0,
    default_max_level=DEFAULT_MAX_LEVEL,
)

VOICE_PARAMS: Final[CurveParams] = CurveParams(
    A=18,
    B=0.36,
    SCALE_LEVEL=100.0,
    default_max_level=DEFAULT_MAX_LEVEL,
)


# 二分探索の回数（0..数千程度ならこれで十分）
_BISECT_ITERS: Final[int] = 32

# 上限なし探索での安全ブレーキ（暴走防止）
_MAX_LEVEL_GUARD: Final[float] = 10_000_000.0

CurveKind = Literal["text", "voice"]


def get_params(kind: CurveKind) -> CurveParams:
    if kind == "text":
        return TEXT_PARAMS
    if kind == "voice":
        return VOICE_PARAMS
    raise ValueError(f"unknown kind: {kind}")


# -------------------------
# Result Model
# -------------------------
@dataclass(frozen=True)
class RankProgress:
    """累計pointsから算出したランク進捗（表示用に便利）。"""
    level: int
    total_points: int

    next_level: int
    points_at_level: int
    points_at_next: int

    earned_into_level: int
    remain_to_next: int

    # 0.0〜1.0（次Lvへどれだけ進んだか）
    ratio: float


# -------------------------
# Internal helpers
# -------------------------
def _norm_max_level(max_level: Optional[int]) -> Optional[int]:
    if max_level is None:
        return None
    if max_level <= 0:
        return 0
    return max_level


def _clamp_level_f(level: float, max_level: Optional[int]) -> float:
    L = float(level)
    if L < 0.0:
        L = 0.0
    if max_level is not None and L > float(max_level):
        L = float(max_level)
    return L


def _effective_max_level(max_level: Optional[int], *, params: CurveParams) -> Optional[int]:
    """
    関数引数 max_level が None なら params.default_max_level を採用。
    関数引数が指定されていればそっち優先。
    """
    if max_level is None:
        return _norm_max_level(params.default_max_level)
    return _norm_max_level(max_level)


# -------------------------
# Core math
# -------------------------
def total_points_for_level(
    level: float,
    *,
    params: CurveParams,
    max_level: Optional[int] = None,
) -> float:
    """
    Lv=level に到達するための累計必要points（float）。
    level は float を許容（逆算・探索用）。

    max_level:
      - int: 指定上限で clamp
      - None: params.default_max_level を採用（Noneなら無制限）
    """
    max_level = _effective_max_level(max_level, params=params)
    L = _clamp_level_f(level, max_level)

    # A*L^2*(1 + B*(L/S)^4)
    return params.A * (L * L) * (1.0 + params.B * ((L / params.SCALE_LEVEL) ** 4))


def total_points_int_for_level(
    level: int,
    *,
    params: CurveParams,
    max_level: Optional[int] = None,
) -> int:
    """Lv=level に到達するための累計必要points（int, 四捨五入）。"""
    max_level = _effective_max_level(max_level, params=params)

    if level <= 0:
        return 0
    if max_level is not None and level >= max_level:
        return int(round(total_points_for_level(float(max_level), params=params, max_level=max_level)))

    return int(round(total_points_for_level(float(level), params=params, max_level=max_level)))


def level_from_points(
    points: int,
    *,
    params: CurveParams,
    max_level: Optional[int] = None,
) -> int:
    """
    累計pointsから現在Lvを算出。
    - max_level が int の場合: 0..max_level
    - max_level が None で params.default_max_level も None の場合: 上限なし（指数探索→二分探索）
    """
    max_level = _effective_max_level(max_level, params=params)
    p = int(points)
    if p <= 0:
        return 0

    # 上限あり：到達済みチェック
    if max_level is not None:
        if p >= total_points_int_for_level(max_level, params=params, max_level=max_level):
            return max_level
        lo = 0.0
        hi = float(max_level)
    else:
        # 上限なし：hi を倍々に増やして Total(hi) > p となる区間を見つける
        lo = 0.0
        hi = float(params.SCALE_LEVEL) if params.SCALE_LEVEL > 0 else 100.0

        while total_points_for_level(hi, params=params, max_level=None) <= p:
            lo = hi
            hi *= 2.0
            if hi > _MAX_LEVEL_GUARD:
                return int(lo)

    # 二分探索
    for _ in range(_BISECT_ITERS):
        mid = (lo + hi) / 2.0
        if total_points_for_level(mid, params=params, max_level=None) <= p:
            lo = mid
        else:
            hi = mid

    lv = int(lo)  # floor
    if lv < 0:
        return 0
    if max_level is not None and lv > max_level:
        return max_level
    return lv


def points_range_for_level(
    level: int,
    *,
    params: CurveParams,
    max_level: Optional[int] = None,
) -> Tuple[int, int]:
    """
    指定Lvの区間 [points_at_level, points_at_next) を返す。
    level=0 の場合は [0, Total(1))。

    max_level:
      - int: level>=max_level の場合は両端同値（次がない）
      - None: 上限なしなので常に「次」が存在（default_max_level=None のとき）
    """
    max_level = _effective_max_level(max_level, params=params)

    if level <= 0:
        return (0, total_points_int_for_level(1, params=params, max_level=max_level))

    if max_level is not None and level >= max_level:
        p = total_points_int_for_level(max_level, params=params, max_level=max_level)
        return (p, p)

    p0 = total_points_int_for_level(level, params=params, max_level=max_level)
    p1 = total_points_int_for_level(level + 1, params=params, max_level=max_level)
    return (p0, p1)


def points_to_next_level(
    points: int,
    *,
    params: CurveParams,
    max_level: Optional[int] = None,
) -> int:
    """現在pointsから次Lvまでの残points（上限到達時は0）。"""
    max_level = _effective_max_level(max_level, params=params)
    lv = level_from_points(points, params=params, max_level=max_level)

    if max_level is not None and lv >= max_level:
        return 0

    _, p_next = points_range_for_level(lv, params=params, max_level=max_level)
    remain = p_next - int(points)
    return 0 if remain < 0 else remain


def progress_from_points(
    points: int,
    *,
    params: CurveParams,
    max_level: Optional[int] = None,
) -> RankProgress:
    """
    pointsから、現在Lv・次Lvまでの残量・進捗率をまとめて返す。
    max_level=None かつ params.default_max_level=None なら「無限レベル」扱い。
    """
    max_level = _effective_max_level(max_level, params=params)
    total = max(0, int(points))
    lv = level_from_points(total, params=params, max_level=max_level)

    p_lv, p_next = points_range_for_level(lv, params=params, max_level=max_level)
    next_lv = lv + 1

    # 上限ありでMAX到達
    if max_level is not None and lv >= max_level:
        return RankProgress(
            level=max_level,
            total_points=total,
            next_level=max_level,
            points_at_level=p_lv,
            points_at_next=p_next,
            earned_into_level=0,
            remain_to_next=0,
            ratio=1.0,
        )

    earned = total - p_lv
    remain = p_next - total
    span = max(1, (p_next - p_lv))  # 0割回避
    ratio = earned / span

    # 安全クランプ（丸め誤差対策）
    if earned < 0:
        earned = 0
    if remain < 0:
        remain = 0
    if ratio < 0.0:
        ratio = 0.0
    if ratio > 1.0:
        ratio = 1.0

    return RankProgress(
        level=lv,
        total_points=total,
        next_level=next_lv,
        points_at_level=p_lv,
        points_at_next=p_next,
        earned_into_level=earned,
        remain_to_next=remain,
        ratio=ratio,
    )


# -------------------------
# Optional helpers (string)
# -------------------------
def format_progress_line(
    points: int,
    *,
    params: CurveParams,
    max_level: Optional[int] = None,
) -> str:
    """
    例:
      - max_level=100: "Lv12 (1234pt) / 次Lvまで 56pt (78.1%)"
      - 無制限:        "Lv123 (99999pt) / 次Lvまで ..."
    """
    pr = progress_from_points(points, params=params, max_level=max_level)
    max_level = _effective_max_level(max_level, params=params)

    if max_level is not None and pr.level >= max_level:
        return f"Lv{pr.level} ({pr.total_points}pt) / MAX"

    pct = pr.ratio * 100.0
    return f"Lv{pr.level} ({pr.total_points}pt) / 次Lvまで {pr.remain_to_next}pt ({pct:.1f}%)"


# -------------------------
# Convenience wrappers (kind="text"/"voice")
# -------------------------
def total_points_for_level_kind(level: float, *, kind: CurveKind, max_level: Optional[int] = None) -> float:
    return total_points_for_level(level, params=get_params(kind), max_level=max_level)


def total_points_int_for_level_kind(level: int, *, kind: CurveKind, max_level: Optional[int] = None) -> int:
    return total_points_int_for_level(level, params=get_params(kind), max_level=max_level)


def level_from_points_kind(points: int, *, kind: CurveKind, max_level: Optional[int] = None) -> int:
    return level_from_points(points, params=get_params(kind), max_level=max_level)


def points_range_for_level_kind(level: int, *, kind: CurveKind, max_level: Optional[int] = None) -> Tuple[int, int]:
    return points_range_for_level(level, params=get_params(kind), max_level=max_level)


def points_to_next_level_kind(points: int, *, kind: CurveKind, max_level: Optional[int] = None) -> int:
    return points_to_next_level(points, params=get_params(kind), max_level=max_level)


def progress_from_points_kind(points: int, *, kind: CurveKind, max_level: Optional[int] = None) -> RankProgress:
    return progress_from_points(points, params=get_params(kind), max_level=max_level)


def format_progress_line_kind(points: int, *, kind: CurveKind, max_level: Optional[int] = None) -> str:
    return format_progress_line(points, params=get_params(kind), max_level=max_level)


# ---------------------------------------------------------
# Debug
# ---------------------------------------------------------
if __name__ == "__main__":
    # TEXT: Lv1..10 の累計と増分
    print("== TEXT ==")
    prev = 0
    for L in range(1, 11):
        cur = total_points_int_for_level(L, params=TEXT_PARAMS)
        inc = cur - prev
        print(f"Lv{L:02d}: total={cur:6d}  inc={inc:4d}")
        prev = cur

    # VOICE: Lv1..10 の累計と増分
    print("\n== VOICE ==")
    prev = 0
    for L in range(1, 11):
        cur = total_points_int_for_level(L, params=VOICE_PARAMS)
        inc = cur - prev
        print(f"Lv{L:02d}: total={cur:6d}  inc={inc:4d}")
        prev = cur

    # 進捗例
    print("\n== SAMPLE ==")
    sample_text = 6560
    print("TEXT :", format_progress_line(sample_text, params=TEXT_PARAMS))
    sample_voice = 25590
    print("VOICE:", format_progress_line(sample_voice, params=VOICE_PARAMS))
