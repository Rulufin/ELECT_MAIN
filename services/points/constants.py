# services/points/constants.py

from __future__ import annotations

from discord import SelectOption

from services.points.enums import Points_Type


# =========================================================
# request
# =========================================================

REQUEST_CODE_PUBLIC = "01"
REQUEST_NOTE_PUBLIC = "01. 公開プレイ"
REQUEST_POINT_PUBLIC = 100

REQUEST_OP = [
    SelectOption(
        label=REQUEST_NOTE_PUBLIC,
        value=REQUEST_CODE_PUBLIC,
        description=str(REQUEST_POINT_PUBLIC),
    ),
]


# =========================================================
# check
# =========================================================

CHECK_PERIOD_WEEKLY = "Weekly"
CHECK_PERIOD_MONTHLY = "Monthly"
CHECK_PERIOD_ALL = "All"

CHECK_OP = [
    SelectOption(
        label="01. 1週間",
        value=CHECK_PERIOD_WEEKLY,
        description="週間集計",
    ),
    SelectOption(
        label="02. 今月",
        value=CHECK_PERIOD_MONTHLY,
        description="月間集計",
    ),
    SelectOption(
        label="03. 全体",
        value=CHECK_PERIOD_ALL,
        description="累計集計",
    ),
]


# =========================================================
# use
# =========================================================

USE_OP = [
    SelectOption(label="01-01. アイコンor絵文字作成", value="01-01", description="3,000"),
    SelectOption(label="02-01. 個人TC作成", value="02-01", description="1,000"),
    SelectOption(label="03-01. 専用ロール作成", value="03-01", description="1,000"),
    SelectOption(label="03-02. 専用ロール名変更", value="03-02", description="1,000"),
    SelectOption(label="03-03. 専用ロール色変更", value="03-03", description="1,000"),
    SelectOption(label="03-04. 専用ロールスタイル強化", value="03-04", description="1,000"),
    SelectOption(label="03-05. 専用ロールアイコン付与", value="03-05", description="1,000"),
    SelectOption(label="99-01. かーくんにネタを振れる", value="99-01", description="500"),
    SelectOption(label="99-02. 山葵の晩ごはんレシピ", value="99-02", description="500"),
]

USE_OP_MAP: dict[str, SelectOption] = {
    option.value: option
    for option in USE_OP
}


# =========================================================
# use group
# =========================================================

USE_GROUP_MAP: dict[str, str] = {
    "01": "CONTENT",
    "02": "CHANNEL",
    "03": "ROLE",
    "99": "FUN",
}


# =========================================================
# use event type
# =========================================================

USE_EVENT_TYPE_MAP: dict[str, Points_Type] = {
    "01-01": Points_Type.USE_ICON_EMOJI,
    "02-01": Points_Type.USE_PRIVATE_TC,
    "03-01": Points_Type.USE_ROLE_CREATE,
    "03-02": Points_Type.USE_ROLE_RENAME,
    "03-03": Points_Type.USE_ROLE_COLOR,
    "03-04": Points_Type.USE_ROLE_STYLE,
    "03-05": Points_Type.USE_ROLE_ICON,
    "99-01": Points_Type.USE_FUN_REQUEST,
    "99-02": Points_Type.USE_FUN_REQUEST,
}


# =========================================================
# thread display
# =========================================================

THREAD_NAME_MAP: dict[str, tuple[str, str]] = {
    "01": ("📌ICON", "アイコン作成"),
    "02": ("📌TC", "個人TC作成"),
    "03": ("📌ROLE", "専用ロール"),
    "99": ("📌FUN", "ネタ依頼"),
}


# =========================================================
# helpers
# =========================================================

def get_use_option(value: str) -> SelectOption | None:
    return USE_OP_MAP.get(value)


def parse_price_text(price_text: str) -> int:
    return int((price_text or "0").replace(",", "").strip())


def split_group_code(value: str) -> str:
    return value.split("-")[0]


def get_use_event_type(value: str) -> Points_Type | None:
    return USE_EVENT_TYPE_MAP.get(value)


def get_thread_info(value: str) -> tuple[str, str, Points_Type]:
    group_code = split_group_code(value)
    prefix, title = THREAD_NAME_MAP.get(group_code, ("📌ETC", "その他"))

    event_type = get_use_event_type(value)
    if event_type is None:
        raise ValueError(f"unknown use event type: {value}")

    return prefix, title, event_type