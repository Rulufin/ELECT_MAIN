# on_event/on_voice/logger.py

import logging
from typing import Optional

from discord import Member, VoiceState

from firestores.fs_voice_log import FS_Voice_Log
from .configs import NOT_CONNECT_VC_IDS
from .context import VoiceStateContext

logger = logging.getLogger(__name__)

FILENAME = "on_voice_state_main"


class VoiceLogService:
    """
    VC の JOIN / LEAVE / MOVE / MUTE を Firestore に記録するサービス。
    ここでは「ログを書くこと」だけに責務を限定する。
    """

    def __init__(self, fs_voice_log: Optional[FS_Voice_Log] = None):
        # 外から渡されなければ自前でインスタンスを作る
        self.fs_voice_log = fs_voice_log or FS_Voice_Log()

    # -----------------------------
    # JOIN / LEAVE / MOVE
    # -----------------------------
    async def log_channel_changes(self, ctx: VoiceStateContext) -> None:
        """
        接続 / 切断 / 移動のイベントを VC_LOG に書き込む。
        """
        member: Member = ctx.member
        guild = ctx.guild
        before_ch = ctx.before_ch
        after_ch = ctx.after_ch
        now = ctx.now

        before_excluded = ctx.before_excluded
        after_excluded = ctx.after_excluded

        # ---- JOIN: None → 何か ----
        if before_ch is None and after_ch is not None:
            if after_excluded:
                return

            after_vs: VoiceState = ctx.after

            await self.fs_voice_log.log_join(
                vc_id=after_ch.id,
                guild_id=guild.id,
                user_id=member.id,
                ts=now,
                from_channel_id=None,
                is_self_mute=after_vs.self_mute,
                is_self_deaf=after_vs.self_deaf,
                is_server_mute=after_vs.mute,
                is_server_deaf=after_vs.deaf,
            )
            logger.info(f"[JOIN] {member} → {after_ch.id}")
            return

        # ---- LEAVE: 何か → None ----
        if before_ch is not None and after_ch is None:
            if before_excluded:
                return

            before_vs: VoiceState = ctx.before

            await self.fs_voice_log.log_leave(
                vc_id=before_ch.id,
                user_id=member.id,
                ts=now,
                to_channel_id=None,
                is_self_mute=before_vs.self_mute,
                is_self_deaf=before_vs.self_deaf,
                is_server_mute=before_vs.mute,
                is_server_deaf=before_vs.deaf,
            )
            logger.info(f"[LEAVE] {member} ← {before_ch.id}")
            return

        # ---- MOVE: 何か → 何か（idが違う）----
        if (
            before_ch is not None
            and after_ch is not None
            and before_ch.id != after_ch.id
        ):
            before_vs: VoiceState = ctx.before
            after_vs: VoiceState = ctx.after

            # 除外 → 除外 は何も記録しない
            if before_excluded and after_excluded:
                return

            # 除外 → 対象: JOINのみ記録
            if before_excluded and not after_excluded:
                await self.fs_voice_log.log_join(
                    vc_id=after_ch.id,
                    guild_id=guild.id,
                    user_id=member.id,
                    ts=now,
                    from_channel_id=before_ch.id,
                    is_self_mute=after_vs.self_mute,
                    is_self_deaf=after_vs.self_deaf,
                    is_server_mute=after_vs.mute,
                    is_server_deaf=after_vs.deaf,
                )
                logger.info(
                    f"[MOVE / JOIN only] {member}: {before_ch.id} → {after_ch.id}"
                )
                return

            # 対象 → 除外: LEAVEのみ記録
            if not before_excluded and after_excluded:
                await self.fs_voice_log.log_leave(
                    vc_id=before_ch.id,
                    user_id=member.id,
                    ts=now,
                    to_channel_id=after_ch.id,
                    is_self_mute=before_vs.self_mute,
                    is_self_deaf=before_vs.self_deaf,
                    is_server_mute=before_vs.mute,
                    is_server_deaf=before_vs.deaf,
                )
                logger.info(
                    f"[MOVE / LEAVE only] {member}: {before_ch.id} → {after_ch.id}"
                )
                return

            # 両方 対象VC: LEAVE + JOIN 両方記録
            await self.fs_voice_log.log_leave(
                vc_id=before_ch.id,
                user_id=member.id,
                ts=now,
                to_channel_id=after_ch.id,
                is_self_mute=before_vs.self_mute,
                is_self_deaf=before_vs.self_deaf,
                is_server_mute=before_vs.mute,
                is_server_deaf=before_vs.deaf,
            )
            await self.fs_voice_log.log_join(
                vc_id=after_ch.id,
                guild_id=guild.id,
                user_id=member.id,
                ts=now,
                from_channel_id=before_ch.id,
                is_self_mute=after_vs.self_mute,
                is_self_deaf=after_vs.self_deaf,
                is_server_mute=after_vs.mute,
                is_server_deaf=after_vs.deaf,
            )
            logger.info(
                f"[MOVE] {member}: {before_ch.id} → {after_ch.id}"
            )

    # -----------------------------
    # MUTE LOG
    # -----------------------------
    async def log_mute_changes(self, ctx: VoiceStateContext) -> None:
        """
        ミュート状態の変化（MUTE_ON / MUTE_OFF）を VC_LOG に書き込む。
        """
        member: Member = ctx.member
        before: VoiceState = ctx.before
        after: VoiceState = ctx.after
        now = ctx.now

        def effective(vs: VoiceState) -> bool:
            return vs.self_mute or vs.self_deaf or vs.mute or vs.deaf

        before_eff = effective(before)
        after_eff = effective(after)

        current_ch = ctx.after_ch or ctx.before_ch
        if current_ch is None:
            return

        # 現在いるVCが除外対象なら、ミュートログも記録しない
        if current_ch.id in NOT_CONNECT_VC_IDS:
            return

        # 変化なし
        if before_eff == after_eff:
            return

        if after_eff:
            # ミュート ON
            await self.fs_voice_log.log_mute_on(
                vc_id=current_ch.id,
                user_id=member.id,
                ts=now,
                is_self_mute=after.self_mute,
                is_self_deaf=after.self_deaf,
                is_server_mute=after.mute,
                is_server_deaf=after.deaf,
            )
            logger.info(f"[MUTE_ON] {member} @ {current_ch.id}")
        else:
            # ミュート OFF
            await self.fs_voice_log.log_mute_off(
                vc_id=current_ch.id,
                user_id=member.id,
                ts=now,
                is_self_mute=after.self_mute,
                is_self_deaf=after.self_deaf,
                is_server_mute=after.mute,
                is_server_deaf=after.deaf,
            )
            logger.info(f"[MUTE_OFF] {member} @ {current_ch.id}")
