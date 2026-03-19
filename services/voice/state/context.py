from __future__ import annotations

from dataclasses import dataclass

from firestores.fs_vc_tc_sync import FS_VC_TC_SYNC
from firestores.fs_voice_log import FS_Voice_Log


@dataclass
class VoiceContext:
    fs_vc_tc_sync: FS_VC_TC_SYNC
    fs_voice_log: FS_Voice_Log
