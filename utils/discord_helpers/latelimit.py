# utils/ratelimit.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

# (key, user_id) -> last_used_at
_button_last_used: Dict[Tuple[str, int], datetime] = {}

def check_button_cooldown(
    *,
    user_id: int,
    key: str,
    cooldown_seconds: int,
) -> tuple[bool, float]:
    """
    ボタン用の簡易クールダウン判定。

    Parameters
    ----------
    user_id : int
        押したユーザーID
    key : str
        ボタンの種類を表すキー（custom_id や FILENAME など好きな単位）
    cooldown_seconds : int
        クールダウン秒数

    Returns
    -------
    (ok, remaining)
        ok: True  -> 処理して良い
            False -> クールダウン中
        remaining: 残りクールダウン秒数（ok=True の場合は 0）
    """
    now = datetime.now(timezone.utc)
    cooldown = timedelta(seconds=cooldown_seconds)

    map_key = (key, user_id)
    last = _button_last_used.get(map_key)

    if last is None or (now - last) >= cooldown:
        _button_last_used[map_key] = now
        return True, 0.0

    # まだクールダウン中
    remaining = (cooldown - (now - last)).total_seconds()
    return False, remaining
