from __future__ import annotations

from typing import Any, Dict, List, Optional
from utils.enum import Genre_Type

def format_genre_totals(
    totals_by_genre: Dict[str, Any],
    *,
    drop_zero: bool = True,
    sort_desc: bool = True,
    max_items: Optional[int] = None,
    use_enum_label: bool = True,
) -> List[Dict[str, int | str]]:
    """
    {"Text": 120, "Voice": 30} -> [{"name":"Text","points":120}, ...]
    """
    items: List[Dict[str, int | str]] = []

    for raw_name, raw_points in (totals_by_genre or {}).items():
        name = str(raw_name)
        points = int(raw_points or 0)

        if drop_zero and points == 0:
            continue

        # Genre_Type を使って表示名を正規化したい場合
        if use_enum_label:
            try:
                # "Text" / "TC" など、value 側に一致する前提
                gt = Genre_Type(name)  # type: ignore[arg-type]
                name = gt.value
            except Exception:
                # 未知のgenreはそのまま表示
                pass

        items.append({"name": name, "points": points})

    if sort_desc:
        items.sort(key=lambda x: int(x["points"]), reverse=True)
    else:
        items.sort(key=lambda x: str(x["name"]))

    if max_items is not None:
        items = items[: int(max_items)]

    return items
