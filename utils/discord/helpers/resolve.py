from __future__ import annotations

from typing import Optional, TypeVar
import re
import logging

import discord
from discord import (
    CategoryChannel,
    ForumChannel,
    Guild,
    GuildSticker,
    Interaction,
    Member,
    Message,
    Role,
    StageChannel,
    TextChannel,
    Thread,
    User,
    VoiceChannel,
)
from discord.abc import GuildChannel, Messageable
from discord.ext import commands

logger = logging.getLogger(__name__)
USER_ID_RE = re.compile(r"\d{15,25}")

T = TypeVar("T")


# ─────────────
# Internal
# ─────────────

async def _safe_fetch(coro) -> Optional[T]:
    try:
        return await coro
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


# ─────────────
# Guild
# ─────────────

async def resolve_guild(
    bot: commands.Bot,
    guild_id: Optional[int],
) -> Optional[Guild]:
    if guild_id is None:
        return None

    guild = bot.get_guild(guild_id)
    if guild is not None:
        return guild

    return await _safe_fetch(bot.fetch_guild(guild_id))


# ─────────────
# User / Member
# ─────────────

async def resolve_user(
    bot: commands.Bot,
    user_id: Optional[int],
) -> Optional[User]:
    if user_id is None:
        return None

    user = bot.get_user(user_id)
    if user is not None:
        return user

    return await _safe_fetch(bot.fetch_user(user_id))


async def resolve_member(
    guild: Optional[Guild],
    user_id: Optional[int],
    *,
    allow_bot: bool = False,
) -> Optional[Member]:
    if guild is None or user_id is None:
        return None

    member = guild.get_member(user_id)
    if member is None:
        member = await _safe_fetch(guild.fetch_member(user_id))

    if member is None:
        return None

    if not allow_bot and member.bot:
        return None

    return member

async def resolve_member_from_value(
    guild: Guild,
    value: str,
) -> Optional[Member]:
    match = USER_ID_RE.search(value or "")
    if not match:
        return None

    user_id = int(match.group())

    member = guild.get_member(user_id)
    if member is not None:
        return member

    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None
    except discord.HTTPException:
        logger.exception("failed to fetch member: %s", user_id)
        return None

async def resolve_target_member(
    guild: Optional[discord.Guild],
    user_id: Optional[int],
) -> Optional[discord.Member]:
    if guild is None or user_id is None:
        return None

    member = guild.get_member(user_id)
    if member is not None:
        return member

    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None
    except discord.Forbidden:
        return None
    except discord.HTTPException:
        logger.exception("[%s] failed to fetch member: %s", user_id)
        return None
    

# ─────────────
# Role / Emoji / Sticker
# ─────────────

async def resolve_role(
    guild: Optional[Guild],
    role_id: Optional[int],
) -> Optional[Role]:
    if guild is None or role_id is None:
        return None

    role = guild.get_role(role_id)
    if role is not None:
        return role

    fetch_role = getattr(guild, "fetch_role", None)
    if callable(fetch_role):
        fetched = await _safe_fetch(fetch_role(role_id))
        if isinstance(fetched, Role):
            return fetched

    fetch_roles = getattr(guild, "fetch_roles", None)
    if callable(fetch_roles):
        fetched_roles = await _safe_fetch(fetch_roles())
        if fetched_roles:
            return discord.utils.get(fetched_roles, id=role_id)

    return None


async def resolve_emoji(
    guild: Optional[Guild],
    emoji_id: Optional[int],
) -> Optional[discord.Emoji]:
    if guild is None or emoji_id is None:
        return None

    emoji = guild.get_emoji(emoji_id)
    if emoji is not None:
        return emoji

    fetch_emoji = getattr(guild, "fetch_emoji", None)
    if callable(fetch_emoji):
        fetched = await _safe_fetch(fetch_emoji(emoji_id))
        if isinstance(fetched, discord.Emoji):
            return fetched

    fetch_emojis = getattr(guild, "fetch_emojis", None)
    if callable(fetch_emojis):
        fetched_emojis = await _safe_fetch(fetch_emojis())
        if fetched_emojis:
            return discord.utils.get(fetched_emojis, id=emoji_id)

    return None


async def resolve_sticker(
    guild: Optional[Guild],
    sticker_id: Optional[int],
) -> Optional[GuildSticker]:
    if guild is None or sticker_id is None:
        return None

    sticker = guild.get_sticker(sticker_id)
    if sticker is not None:
        return sticker

    fetch_sticker = getattr(guild, "fetch_sticker", None)
    if callable(fetch_sticker):
        fetched = await _safe_fetch(fetch_sticker(sticker_id))
        if isinstance(fetched, GuildSticker):
            return fetched

    fetch_stickers = getattr(guild, "fetch_stickers", None)
    if callable(fetch_stickers):
        fetched_stickers = await _safe_fetch(fetch_stickers())
        if fetched_stickers:
            return discord.utils.get(fetched_stickers, id=sticker_id)

    return None


# ─────────────
# Channel : Base
# ─────────────

async def resolve_channel(
    guild: Optional[Guild],
    channel_id: Optional[int],
) -> Optional[GuildChannel | Thread]:
    if guild is None or channel_id is None:
        return None

    thread_obj = guild.get_thread(channel_id)
    if thread_obj is not None:
        return thread_obj

    channel_obj = guild.get_channel(channel_id)
    if channel_obj is not None:
        return channel_obj

    fetched_obj = await _safe_fetch(guild.fetch_channel(channel_id))
    if isinstance(fetched_obj, (GuildChannel, Thread)):
        return fetched_obj

    return None


# ─────────────
# Channel : Text
# ─────────────

async def resolve_text_channel(
    guild: Optional[Guild],
    channel_id: Optional[int],
) -> Optional[TextChannel]:
    channel_obj = await resolve_channel(guild, channel_id)
    if isinstance(channel_obj, TextChannel):
        return channel_obj
    return None


# ─────────────
# Channel : Voice
# ─────────────

async def resolve_voice_channel(
    guild: Optional[Guild],
    channel_id: Optional[int],
) -> Optional[VoiceChannel]:
    channel_obj = await resolve_channel(guild, channel_id)
    if isinstance(channel_obj, VoiceChannel):
        return channel_obj
    return None


# ─────────────
# Channel : Stage
# ─────────────

async def resolve_stage_channel(
    guild: Optional[Guild],
    channel_id: Optional[int],
) -> Optional[StageChannel]:
    channel_obj = await resolve_channel(guild, channel_id)
    if isinstance(channel_obj, StageChannel):
        return channel_obj
    return None


# ─────────────
# Channel : Forum
# ─────────────

async def resolve_forum_channel(
    guild: Optional[Guild],
    channel_id: Optional[int],
) -> Optional[ForumChannel]:
    channel_obj = await resolve_channel(guild, channel_id)
    if isinstance(channel_obj, ForumChannel):
        return channel_obj
    return None


# ─────────────
# Channel : Category
# ─────────────

async def resolve_category_channel(
    guild: Optional[Guild],
    channel_id: Optional[int],
) -> Optional[CategoryChannel]:
    channel_obj = await resolve_channel(guild, channel_id)
    if isinstance(channel_obj, CategoryChannel):
        return channel_obj
    return None


# ─────────────
# Channel : Thread
# ─────────────

async def resolve_thread(
    guild: Optional[Guild],
    thread_id: Optional[int],
) -> Optional[Thread]:
    channel_obj = await resolve_channel(guild, thread_id)
    if isinstance(channel_obj, Thread):
        return channel_obj
    return None


# ─────────────
# Channel : VoiceLike
# ─────────────

async def resolve_voice_like_channel(
    guild: Optional[Guild],
    channel_id: Optional[int],
) -> Optional[VoiceChannel | StageChannel]:
    channel_obj = await resolve_channel(guild, channel_id)
    if isinstance(channel_obj, (VoiceChannel, StageChannel)):
        return channel_obj
    return None


# ─────────────
# Message
# ─────────────

async def resolve_message(
    channel: Optional[Messageable],
    message_id: Optional[int],
) -> Optional[Message]:
    if channel is None or message_id is None:
        return None

    try:
        return await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        return None


# ─────────────
# Interaction : Base
# ─────────────

async def resolve_interaction_guild(
    interaction: Interaction,
) -> Optional[Guild]:
    if interaction.guild is not None:
        return interaction.guild

    guild_id = interaction.guild_id
    if guild_id is None:
        return None

    client = interaction.client
    if not isinstance(client, commands.Bot):
        return None

    return await resolve_guild(client, guild_id)


async def resolve_interaction_member(
    interaction: Interaction,
    *,
    allow_bot: bool = False,
) -> Optional[Member]:
    if isinstance(interaction.user, Member):
        if not allow_bot and interaction.user.bot:
            return None
        return interaction.user

    guild = await resolve_interaction_guild(interaction)
    if guild is None:
        return None

    return await resolve_member(
        guild,
        getattr(interaction.user, "id", None),
        allow_bot=allow_bot,
    )


async def resolve_interaction_channel(
    interaction: Interaction,
) -> Optional[GuildChannel | Thread]:
    if isinstance(interaction.channel, (GuildChannel, Thread)):
        return interaction.channel

    guild = await resolve_interaction_guild(interaction)
    if guild is None:
        return None

    return await resolve_channel(guild, interaction.channel_id)


# ─────────────
# Interaction : Typed Channel
# ─────────────

async def resolve_interaction_text_channel(
    interaction: Interaction,
) -> Optional[TextChannel]:
    channel_obj = await resolve_interaction_channel(interaction)
    if isinstance(channel_obj, TextChannel):
        return channel_obj
    return None


async def resolve_interaction_voice_channel(
    interaction: Interaction,
) -> Optional[VoiceChannel]:
    channel_obj = await resolve_interaction_channel(interaction)
    if isinstance(channel_obj, VoiceChannel):
        return channel_obj
    return None


async def resolve_interaction_thread(
    interaction: Interaction,
) -> Optional[Thread]:
    channel_obj = await resolve_interaction_channel(interaction)
    if isinstance(channel_obj, Thread):
        return channel_obj
    return None


async def resolve_interaction_forum_channel(
    interaction: Interaction,
) -> Optional[ForumChannel]:
    channel_obj = await resolve_interaction_channel(interaction)
    if isinstance(channel_obj, ForumChannel):
        return channel_obj
    return None


# ─────────────
# Type Narrow Helpers
# ─────────────

def as_text_channel(
    channel_obj: Optional[GuildChannel | Thread],
) -> Optional[TextChannel]:
    if isinstance(channel_obj, TextChannel):
        return channel_obj
    return None


def as_voice_channel(
    channel_obj: Optional[GuildChannel | Thread],
) -> Optional[VoiceChannel]:
    if isinstance(channel_obj, VoiceChannel):
        return channel_obj
    return None


def as_stage_channel(
    channel_obj: Optional[GuildChannel | Thread],
) -> Optional[StageChannel]:
    if isinstance(channel_obj, StageChannel):
        return channel_obj
    return None


def as_forum_channel(
    channel_obj: Optional[GuildChannel | Thread],
) -> Optional[ForumChannel]:
    if isinstance(channel_obj, ForumChannel):
        return channel_obj
    return None


def as_category_channel(
    channel_obj: Optional[GuildChannel | Thread],
) -> Optional[CategoryChannel]:
    if isinstance(channel_obj, CategoryChannel):
        return channel_obj
    return None


def as_thread(
    channel_obj: Optional[GuildChannel | Thread],
) -> Optional[Thread]:
    if isinstance(channel_obj, Thread):
        return channel_obj
    return None


def as_voice_like_channel(
    channel_obj: Optional[GuildChannel | Thread],
) -> Optional[VoiceChannel | StageChannel]:
    if isinstance(channel_obj, (VoiceChannel, StageChannel)):
        return channel_obj
    return None


