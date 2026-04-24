from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Final, FrozenSet


@dataclass(frozen=True)
class TalkHistoryConfig:
    """
    VCで「話したことがある」とみなすための設定。
    """

    enabled: bool = True

    qualify_seconds: float = 300.0
    flush_seconds: float = 30.0
    recent_write_ttl: float = 15.0
    min_write_seconds: float = 1.0

    allow_bots: bool = False
    allow_self_deaf: bool = False
    allow_self_mute: bool = True
    allow_stage_channel: bool = True

    allowed_channel_ids: FrozenSet[int] = field(default_factory=frozenset)
    denied_channel_ids: FrozenSet[int] = field(default_factory=frozenset)

    required_role_ids: FrozenSet[int] = field(default_factory=frozenset)
    denied_role_ids: FrozenSet[int] = field(default_factory=frozenset)


DEFAULT_TALK_HISTORY_CONFIG: Final[TalkHistoryConfig] = TalkHistoryConfig(
    enabled=True,
    qualify_seconds=300.0,
    flush_seconds=30.0,
    recent_write_ttl=15.0,
    min_write_seconds=1.0,
    allow_bots=False,
    allow_self_deaf=False,
    allow_self_mute=True,
    allow_stage_channel=True,
    allowed_channel_ids=frozenset(),
    denied_channel_ids=frozenset(),
    required_role_ids=frozenset(),
    denied_role_ids=frozenset(),
)

# 例:
# 仮メンバー審査カテゴリは15分必要
# 雑談カテゴリは5分
CATEGORY_TALK_HISTORY_CONFIGS: Final[dict[int, TalkHistoryConfig]] = {
    # 審査カテゴリ
    1424277873463787550: replace(
        DEFAULT_TALK_HISTORY_CONFIG,
        enabled=False
    ),

    # 公開カテゴリ
   1423782520322789407: replace(
        DEFAULT_TALK_HISTORY_CONFIG,
        allow_self_deaf=False,
        allow_self_mute=False,
        required_role_ids=frozenset(),
    ),
}