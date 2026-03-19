import discord
import logging

from utils.discord_helpers.user_ids import coerce_user_ids

async def fetch_thread_human_members(
    thread: discord.Thread,
    guild: discord.Guild,
    *,
    logger: logging.Logger | None = None,
) -> list[discord.Member]:
    try:
        fetched = await thread.fetch_members()
    except (discord.Forbidden, discord.HTTPException) as e:
        if logger:
            logger.warning("[Exclusion] fetch_members failed: %r", e)
        fetched = []

    user_ids = coerce_user_ids(fetched)

    members: list[discord.Member] = []
    for uid in user_ids:
        m = guild.get_member(uid)
        if m is None:
            try:
                m = await guild.fetch_member(uid)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        if m.bot:
            continue
        members.append(m)

    # 見た目安定
    members.sort(key=lambda m: m.display_name.lower())
    return members
