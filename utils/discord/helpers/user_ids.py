import re
from typing import Iterable, Any, Optional

from discord import Embed

MENTION_ID_RE = re.compile(r"<@!?(?P<id>\d+)>")

def coerce_user_ids(obj: Any) -> set[int]:
    """
    obj が
    - Member / User / ThreadMember / Snowflake っぽいもの
    - list/tuple/set などの iterable
    - "01. name（<@123>）" のような文字列
    いずれでも user_id(set[int]) を返す
    """
    ids: set[int] = set()

    if obj is None:
        return ids

    # 文字列: mention から
    if isinstance(obj, str):
        return {int(m.group("id")) for m in MENTION_ID_RE.finditer(obj)}

    # iterable（ただし文字列は除外済）
    if isinstance(obj, (list, tuple, set)):
        for x in obj:
            ids |= coerce_user_ids(x)
        return ids

    # ThreadMember: id が user_id になってる（ログより）
    uid = getattr(obj, "user_id", None)
    if isinstance(uid, int):
        ids.add(uid)
        return ids

    # Member/User/ThreadMember: id
    uid = getattr(obj, "id", None)
    if isinstance(uid, int):
        ids.add(uid)
        return ids

    return ids

def coerce_user_ids_or_raw_id(obj: Any) -> set[int]:
    ids = coerce_user_ids(obj)
    if ids:
        return ids

    if isinstance(obj, str):
        s = obj.strip()
        if s.isdigit() and 15 <= len(s) <= 25:
            return {int(s)}

    return set()