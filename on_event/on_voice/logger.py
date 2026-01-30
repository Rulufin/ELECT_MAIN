# on_event/on_voice/logger.py

import logging
from typing import Optional, Dict, Any

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

    ✅ 重要：
    - VCType 判定に必要なので、VC_LOG のトップに category_id を保存する。
      (VC削除後は Discord API から category_id を取れない可能性があるため)

    ✅ owner_user_id：
    - 対象VC（NOT_CONNECT_VC_IDS 以外）に対して、owner_user_id が空なら最初に到達したユーザーを保存する。
      (作成用VCなど対象外VC→MOVEで来るケースも、JOINで来るケースも両対応)
    """

    def __init__(self, fs_voice_log: Optional[FS_Voice_Log] = None):
        self.fs_voice_log = fs_voice_log or FS_Voice_Log()

    # -----------------------------
    # owner helper
    # -----------------------------
    async def _ensure_owner_if_target_vc(self, *, vc_id: int, owner_user_id: int) -> None:
        """
        対象VCの場合のみ、owner_user_id が空なら保存する。
        """
        if vc_id in NOT_CONNECT_VC_IDS:
            return
        await self.fs_voice_log.set_vc_owner_if_empty(vc_id=vc_id, owner_user_id=owner_user_id)

    # -----------------------------
    # JOIN / LEAVE / MOVE
    # -----------------------------
    async def log_channel_changes(self, ctx: VoiceStateContext) -> None:
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

            # ✅ VCドキュメントを確実に作る（トップレベル構造）
            # ✅ category_id を保存
            await self.fs_voice_log.ensure_vc_doc(
                vc_id=after_ch.id,
                guild_id=guild.id,
                created_at=now,
                category_id=after_ch.category_id,
            )

            # ✅ 対象VCなら owner を確定（空なら保存）
            await self._ensure_owner_if_target_vc(vc_id=after_ch.id, owner_user_id=member.id)

            extra: Dict[str, Any] = {
                "guild_id": str(guild.id),
                "category_id": str(after_ch.category_id),
                "from_channel_id": None,
                "to_channel_id": str(after_ch.id),
                "is_self_mute": after_vs.self_mute,
                "is_self_deaf": after_vs.self_deaf,
                "is_server_mute": after_vs.mute,
                "is_server_deaf": after_vs.deaf,
            }

            await self.fs_voice_log.add_event(
                vc_id=after_ch.id,
                user_id=member.id,
                event_type="JOIN",
                ts=now,
                extra=extra,
            )

            logger.info(f"[JOIN] {member} → {after_ch.id} (category_id={after_ch.category_id})")
            return

        # ---- LEAVE: 何か → None ----
        if before_ch is not None and after_ch is None:
            if before_excluded:
                return

            before_vs: VoiceState = ctx.before

            await self.fs_voice_log.ensure_vc_doc(
                vc_id=before_ch.id,
                guild_id=guild.id,
                created_at=now,
                category_id=before_ch.category_id,
            )

            extra: Dict[str, Any] = {
                "guild_id": str(guild.id),
                "category_id": str(before_ch.category_id),
                "from_channel_id": str(before_ch.id),
                "to_channel_id": None,
                "is_self_mute": before_vs.self_mute,
                "is_self_deaf": before_vs.self_deaf,
                "is_server_mute": before_vs.mute,
                "is_server_deaf": before_vs.deaf,
            }

            await self.fs_voice_log.add_event(
                vc_id=before_ch.id,
                user_id=member.id,
                event_type="LEAVE",
                ts=now,
                extra=extra,
            )

            logger.info(f"[LEAVE] {member} ← {before_ch.id} (category_id={before_ch.category_id})")
            return

        # ---- MOVE: 何か → 何か（idが違う）----
        if before_ch is not None and after_ch is not None and before_ch.id != after_ch.id:
            before_vs: VoiceState = ctx.before
            after_vs: VoiceState = ctx.after

            # 除外 → 除外 は何も記録しない
            if before_excluded and after_excluded:
                return

            # 除外 → 対象: JOINのみ記録（ShabeleA の作成用VC→新規VC移動を想定）
            if before_excluded and not after_excluded:
                await self.fs_voice_log.ensure_vc_doc(
                    vc_id=after_ch.id,
                    guild_id=guild.id,
                    created_at=now,
                    category_id=after_ch.category_id,
                )

                # ✅ after が対象VCなら owner を確定（空なら保存）
                await self._ensure_owner_if_target_vc(vc_id=after_ch.id, owner_user_id=member.id)

                extra = {
                    "guild_id": str(guild.id),
                    "category_id": str(after_ch.category_id),
                    "from_channel_id": str(before_ch.id),
                    "to_channel_id": str(after_ch.id),
                    "is_self_mute": after_vs.self_mute,
                    "is_self_deaf": after_vs.self_deaf,
                    "is_server_mute": after_vs.mute,
                    "is_server_deaf": after_vs.deaf,
                }

                await self.fs_voice_log.add_event(
                    vc_id=after_ch.id,
                    user_id=member.id,
                    event_type="JOIN",
                    ts=now,
                    extra=extra,
                )

                logger.info(
                    f"[MOVE / JOIN only] {member}: {before_ch.id} → {after_ch.id} (category_id={after_ch.category_id})"
                )
                return

            # 対象 → 除外: LEAVEのみ記録
            if not before_excluded and after_excluded:
                await self.fs_voice_log.ensure_vc_doc(
                    vc_id=before_ch.id,
                    guild_id=guild.id,
                    created_at=now,
                    category_id=before_ch.category_id,
                )

                extra = {
                    "guild_id": str(guild.id),
                    "category_id": str(before_ch.category_id),
                    "from_channel_id": str(before_ch.id),
                    "to_channel_id": str(after_ch.id),
                    "is_self_mute": before_vs.self_mute,
                    "is_self_deaf": before_vs.self_deaf,
                    "is_server_mute": before_vs.mute,
                    "is_server_deaf": before_vs.deaf,
                }

                await self.fs_voice_log.add_event(
                    vc_id=before_ch.id,
                    user_id=member.id,
                    event_type="LEAVE",
                    ts=now,
                    extra=extra,
                )

                logger.info(
                    f"[MOVE / LEAVE only] {member}: {before_ch.id} → {after_ch.id} (category_id={before_ch.category_id})"
                )
                return

            # 両方 対象VC: LEAVE + JOIN 両方記録
            await self.fs_voice_log.ensure_vc_doc(
                vc_id=before_ch.id,
                guild_id=guild.id,
                created_at=now,
                category_id=before_ch.category_id,
            )
            await self.fs_voice_log.ensure_vc_doc(
                vc_id=after_ch.id,
                guild_id=guild.id,
                created_at=now,
                category_id=after_ch.category_id,
            )

            # ✅ after が対象VCなら owner を確定（空なら保存）
            await self._ensure_owner_if_target_vc(vc_id=after_ch.id, owner_user_id=member.id)

            # LEAVE (before)
            await self.fs_voice_log.add_event(
                vc_id=before_ch.id,
                user_id=member.id,
                event_type="LEAVE",
                ts=now,
                extra={
                    "guild_id": str(guild.id),
                    "category_id": str(before_ch.category_id),
                    "from_channel_id": str(before_ch.id),
                    "to_channel_id": str(after_ch.id),
                    "is_self_mute": before_vs.self_mute,
                    "is_self_deaf": before_vs.self_deaf,
                    "is_server_mute": before_vs.mute,
                    "is_server_deaf": before_vs.deaf,
                },
            )

            # JOIN (after)
            await self.fs_voice_log.add_event(
                vc_id=after_ch.id,
                user_id=member.id,
                event_type="JOIN",
                ts=now,
                extra={
                    "guild_id": str(guild.id),
                    "category_id": str(after_ch.category_id),
                    "from_channel_id": str(before_ch.id),
                    "to_channel_id": str(after_ch.id),
                    "is_self_mute": after_vs.self_mute,
                    "is_self_deaf": after_vs.self_deaf,
                    "is_server_mute": after_vs.mute,
                    "is_server_deaf": after_vs.deaf,
                },
            )

            logger.info(
                f"[MOVE] {member}: {before_ch.id} → {after_ch.id} "
                f"(before_category_id={before_ch.category_id} after_category_id={after_ch.category_id})"
            )
            return

    # -----------------------------
    # MUTE LOG
    # -----------------------------
    async def log_mute_changes(self, ctx: VoiceStateContext) -> None:
        member: Member = ctx.member
        before: VoiceState = ctx.before
        after: VoiceState = ctx.after
        now = ctx.now
        guild = ctx.guild

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

        await self.fs_voice_log.ensure_vc_doc(
            vc_id=current_ch.id,
            guild_id=guild.id,
            created_at=now,
            category_id=current_ch.category_id,
        )

        extra = {
            "guild_id": str(guild.id),
            "category_id": str(current_ch.category_id),
            "is_self_mute": after.self_mute,
            "is_self_deaf": after.self_deaf,
            "is_server_mute": after.mute,
            "is_server_deaf": after.deaf,
        }

        if after_eff:
            await self.fs_voice_log.add_event(
                vc_id=current_ch.id,
                user_id=member.id,
                event_type="MUTE_ON",
                ts=now,
                extra=extra,
            )
            logger.info(f"[MUTE_ON] {member} @ {current_ch.id} (category_id={current_ch.category_id})")
        else:
            await self.fs_voice_log.add_event(
                vc_id=current_ch.id,
                user_id=member.id,
                event_type="MUTE_OFF",
                ts=now,
                extra=extra,
            )
            logger.info(f"[MUTE_OFF] {member} @ {current_ch.id} (category_id={current_ch.category_id})")
