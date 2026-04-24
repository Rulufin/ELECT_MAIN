# services/rank_system/text_points.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Optional
import random
import time


# =========================================================
# Text Points Math (ProBot-like-ish)
# =========================================================
#
# TCのメッセージ投稿に対して、ランダムでポイントを付与する。
#
# ここは「メッセージ → 付与ポイント」を返すだけに寄せる。
# - Bot除外、コマンド除外、チャンネル除外、クールダウン等の判定は
#   on_message 側（または service 側）でやるのがオススメ。
#
# ただし「最低限の判定」をここでやりたい場合に備えて
# いくつかの簡易フィルタも提供する。
# =========================================================


# ---- default range (調整しやすいように定数化) ----
DEFAULT_MIN_POINTS: Final[int] = 15
DEFAULT_MAX_POINTS: Final[int] = 25

# 文字数が短すぎる投稿は対象外にしたい場合
DEFAULT_MIN_CHARS: Final[int] = 3


@dataclass(frozen=True)
class TextPointRule:
    """
    メッセージからポイントを算出するためのルールセット。
    """
    min_points: int = DEFAULT_MIN_POINTS
    max_points: int = DEFAULT_MAX_POINTS

    # 短文除外（0以下なら無効）
    min_chars: int = DEFAULT_MIN_CHARS

    # 連投対策のクールダウン（秒）（0以下なら無効）
    cooldown_seconds: float = 0.0


class TextPointCooldown:
    """
    ユーザー単位の簡易クールダウン管理（メモリ）。
    ※あなたはFirestore運用が多いので、on_message側で管理してもOK。
    """
    def __init__(self) -> None:
        self._last_at: dict[int, float] = {}

    def can_gain(self, user_id: int, *, cooldown_seconds: float, now: Optional[float] = None) -> bool:
        if cooldown_seconds <= 0:
            return True
        t = time.time() if now is None else float(now)
        last = self._last_at.get(int(user_id))
        if last is None:
            return True
        return (t - last) >= cooldown_seconds

    def mark_gained(self, user_id: int, *, now: Optional[float] = None) -> None:
        t = time.time() if now is None else float(now)
        self._last_at[int(user_id)] = t


def calc_text_points(
    content: str,
    *,
    rng: random.Random | None = None,
    rule: TextPointRule = TextPointRule(),
) -> int:
    """
    テキスト内容から付与ポイントを算出する（ランダム）。

    - content が短すぎる場合は 0
    - min_points..max_points の範囲で一様乱数

    on_message 側で「対象メッセージかどうか」を判定したうえで
    最後にこの関数だけ呼ぶ運用がおすすめ。
    """
    if content is None:
        return 0

    s = content.strip()
    if rule.min_chars > 0 and len(s) < rule.min_chars:
        return 0

    lo = int(rule.min_points)
    hi = int(rule.max_points)
    if lo <= 0 or hi <= 0:
        return 0
    if lo > hi:
        lo, hi = hi, lo

    r = rng or random
    return int(r.randint(lo, hi))


def calc_text_points_with_cooldown(
    *,
    user_id: int,
    content: str,
    cooldown: TextPointCooldown,
    rng: random.Random | None = None,
    rule: TextPointRule = TextPointRule(),
    now: Optional[float] = None,
) -> int:
    """
    クールダウン込みの “お手軽版”。

    - cooldown_seconds が 0 なら常に判定OK
    - OKならポイント算出して mark する
    """
    if rule.cooldown_seconds > 0:
        if not cooldown.can_gain(user_id, cooldown_seconds=rule.cooldown_seconds, now=now):
            return 0

    pts = calc_text_points(content, rng=rng, rule=rule)
    if pts > 0 and rule.cooldown_seconds > 0:
        cooldown.mark_gained(user_id, now=now)
    return pts
