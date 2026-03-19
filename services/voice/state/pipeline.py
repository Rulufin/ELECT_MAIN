from __future__ import annotations

import discord
from discord import Member, VoiceState
from typing import Literal

from services.rank_system._rank_config import resolve_vc_rule, is_eligible
from .context import VoiceContext


Action = Literal["leave", "join", "move_leave", "move_join", "state_change"]


def should_write_voice_log(member: Member, action: Action) -> bool:
    # 今はbotはログらない
    if member.bot:
        return False
    return True


async def handle_voice_state(
    bot: discord.Client,
    member: Member,
    before: VoiceState,
    after: VoiceState,
    ctx: VoiceContext,
) -> None:
    before_ch = before.channel
    after_ch = after.channel

    before_rule = resolve_vc_rule(before_ch)
    after_rule = resolve_vc_rule(after_ch)

    before_ok = (before_ch is not None) and before_rule.enabled and is_eligible(member, before_rule)
    after_ok = (after_ch is not None) and after_rule.enabled and is_eligible(member, after_rule)

    # LEAVE
    if before_ok and not after_ok:
        if should_write_voice_log(member, "leave"):
            await ctx.fs_voice_log.close_session(
                guild_id=member.guild.id,
                vc_id=int(before_ch.id),
                user_id=member.id,
                before_state=before,
                note="leave",
            )
        return

    # JOIN
    if after_ok and not before_ok:
        if should_write_voice_log(member, "join"):
            await ctx.fs_voice_log.open_session(
                guild_id=member.guild.id,
                vc_id=int(after_ch.id),
                user_id=member.id,
                after_state=after,
                multiplier=float(after_rule.multiplier),
                ignore_self_mute=bool(after_rule.mic_mute),
                note="join",
            )
        return

    # MOVE
    if before_ok and after_ok and before_ch.id != after_ch.id:
        if should_write_voice_log(member, "move_leave"):
            await ctx.fs_voice_log.close_session(
                guild_id=member.guild.id,
                vc_id=int(before_ch.id),
                user_id=member.id,
                before_state=before,
                note="move_leave",
            )

        if should_write_voice_log(member, "move_join"):
            await ctx.fs_voice_log.open_session(
                guild_id=member.guild.id,
                vc_id=int(after_ch.id),
                user_id=member.id,
                after_state=after,
                multiplier=float(after_rule.multiplier),
                ignore_self_mute=bool(after_rule.mic_mute),
                note="move_join",
            )
        return

    # STAY（mute/deafのみ変化）
    if after_ok:
        if before.self_mute == after.self_mute and before.self_deaf == after.self_deaf:
            return

        if should_write_voice_log(member, "state_change"):
            await ctx.fs_voice_log.toggle_session(
                guild_id=member.guild.id,
                vc_id=int(after_ch.id),
                user_id=member.id,
                before_state=before,
                after_state=after,
                ignore_self_mute=bool(after_rule.mic_mute),
                note="state_change",
            )
        return
