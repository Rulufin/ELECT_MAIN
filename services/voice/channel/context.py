from __future__ import annotations

from dataclasses import dataclass

from firestores.fs_voice_log import FS_Voice_Log
from firestores.fs_rank import FS_Rank


@dataclass
class VoiceChannelContext:
    fs_voice_log: FS_Voice_Log
    fs_rank: FS_Rank
    max_bulk_lines: int = 15

    # ポイント変換設定（必要ならここに寄せる）
    vc_seconds_per_point: int = 60
    vc_round_up: bool = False
