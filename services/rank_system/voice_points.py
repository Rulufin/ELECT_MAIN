from __future__ import annotations

from typing import Final
import math


SECONDS_PER_POINT: Final[int] = 12


def _safe_float(x: float | int) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return v


def seconds_to_points(
    active_seconds: float | int,
    *,
    seconds_per_point: int = SECONDS_PER_POINT,
    round_up: bool = False,
) -> int:
    s = _safe_float(active_seconds)
    if s <= 0:
        return 0

    if seconds_per_point <= 0:
        raise ValueError("seconds_per_point must be > 0")

    value = s / float(seconds_per_point)
    return int(math.ceil(value)) if round_up else int(math.floor(value))


def split_seconds_and_points(
    active_seconds: float | int,
    *,
    seconds_per_point: int = SECONDS_PER_POINT,
    round_up: bool = False,
) -> tuple[int, float]:
    s = _safe_float(active_seconds)
    if s <= 0:
        return 0, 0.0

    if seconds_per_point <= 0:
        raise ValueError("seconds_per_point must be > 0")

    if round_up:
        points = int(math.ceil(s / float(seconds_per_point)))
        return points, 0.0

    points = int(s // seconds_per_point)
    remaining = float(s - (points * seconds_per_point))
    # 念のため
    if remaining < 0:
        remaining = 0.0
    return points, remaining
