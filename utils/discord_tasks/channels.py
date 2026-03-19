# utils/discord/channels.py
from __future__ import annotations

from typing import Optional, Awaitable, Callable

from discord import (
    CategoryChannel,
    ForumChannel,
    Guild,
    PermissionOverwrite,
    TextChannel,
    VoiceChannel,
)
from discord.abc import GuildChannel

from .safe_call import safe_call
from .errors import RateLimitInfo  # ★追加（errors.py 側に定義）
from .buckets import (
    bucket_guild_create_channel,
    bucket_channel_patch,
    bucket_channel_delete,
)

RateLimitNotifier = Callable[[RateLimitInfo], Awaitable[None]]


# =========
# Channel CRUD (GuildChannel)
# =========

async def safe_create_text_channel(
    guild: Guild,
    *,
    name: str,
    category: Optional[CategoryChannel] = None,
    overwrites: Optional[dict[object, PermissionOverwrite]] = None,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> Optional[TextChannel]:
    bucket = bucket_guild_create_channel(guild.id)
    return await safe_call(
        lambda: guild.create_text_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            reason=reason,
        ),
        action="guild.create_text_channel",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )


async def safe_create_voice_channel(
    guild: Guild,
    *,
    name: str,
    category: Optional[CategoryChannel] = None,
    bitrate: Optional[int] = None,
    user_limit: Optional[int] = None,
    overwrites: Optional[dict[object, PermissionOverwrite]] = None,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> Optional[VoiceChannel]:
    bucket = bucket_guild_create_channel(guild.id)
    return await safe_call(
        lambda: guild.create_voice_channel(
            name=name,
            category=category,
            bitrate=bitrate,
            user_limit=user_limit,
            overwrites=overwrites,
            reason=reason,
        ),
        action="guild.create_voice_channel",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )


async def safe_create_forum_channel(
    guild: Guild,
    *,
    name: str,
    category: Optional[CategoryChannel] = None,
    overwrites: Optional[dict[object, PermissionOverwrite]] = None,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> Optional[ForumChannel]:
    bucket = bucket_guild_create_channel(guild.id)
    return await safe_call(
        lambda: guild.create_forum(
            name=name,
            category=category,
            overwrites=overwrites,
            reason=reason,
        ),
        action="guild.create_forum",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )


async def safe_channel_edit(
    channel: GuildChannel,
    *,
    name: Optional[str] = None,
    topic: Optional[str] = None,
    user_limit: Optional[int] = None,
    bitrate: Optional[int] = None,
    reason: Optional[str] = None,
    use_queue: bool = True,
    # ★追加：長い429通知
    on_rate_limit: Optional[RateLimitNotifier] = None,
    notify_threshold: float = 15.0,
) -> Optional[GuildChannel]:
    bucket = bucket_channel_patch(channel.id)

    kwargs = {}
    if name is not None:
        kwargs["name"] = name
    if topic is not None:
        kwargs["topic"] = topic
    if user_limit is not None:
        kwargs["user_limit"] = user_limit
    if bitrate is not None:
        kwargs["bitrate"] = bitrate

    return await safe_call(
        lambda: channel.edit(**kwargs, reason=reason),
        action="channel.edit",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
        # ★PATCH /channels は長くなり得るので route を渡す
        route="PATCH /channels/{channel_id}",
        bucket_key=str(channel.id),
        on_rate_limit=on_rate_limit,
        notify_threshold=notify_threshold,
    )


async def safe_channel_delete(
    channel: GuildChannel,
    *,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> Optional[None]:
    bucket = bucket_channel_delete(channel.id)
    return await safe_call(
        lambda: channel.delete(reason=reason),
        action="channel.delete",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )


async def safe_rename_channel(
    channel: GuildChannel,
    *,
    new_name: str,
    reason: Optional[str] = None,
    use_queue: bool = True,
    # ★追加：長い429通知
    on_rate_limit: Optional[RateLimitNotifier] = None,
    notify_threshold: float = 15.0,
) -> None:
    bucket = bucket_channel_patch(channel.id)
    await safe_call(
        lambda: channel.edit(name=new_name, reason=reason),
        action="channel.edit(name)",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
        route="PATCH /channels/{channel_id}",
        bucket_key=str(channel.id),
        on_rate_limit=on_rate_limit,
        notify_threshold=notify_threshold,
    )
