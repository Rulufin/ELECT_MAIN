# utils/discord/buckets.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from discord import Message
from discord.abc import Messageable

from .queueing import bucket_route_major, serial_channel, serial_message


@dataclass(frozen=True)
class BucketPair:
    bucket_id: str
    serial_id: Optional[str] = None


# ===== Messages (channels/{id}/messages) =====

def bucket_channel_send(channel_id: int) -> BucketPair:
    return BucketPair(
        bucket_id=bucket_route_major(
            "POST",
            "/channels/{channel_id}/messages",
            major_kind="channel",
            major_id=channel_id,
        ),
        serial_id=serial_channel(channel_id),
    )


def bucket_message_edit(channel_id: int, message_id: int) -> BucketPair:
    return BucketPair(
        bucket_id=bucket_route_major(
            "PATCH",
            "/channels/{channel_id}/messages/{message_id}",
            major_kind="channel",
            major_id=channel_id,
        ),
        serial_id=serial_message(message_id),
    )


def bucket_message_delete(channel_id: int, message_id: int) -> BucketPair:
    return BucketPair(
        bucket_id=bucket_route_major(
            "DELETE",
            "/channels/{channel_id}/messages/{message_id}",
            major_kind="channel",
            major_id=channel_id,
        ),
        serial_id=serial_message(message_id),
    )


# ===== Channels (/channels/{id}) =====

def bucket_channel_patch(channel_id: int) -> BucketPair:
    return BucketPair(
        bucket_id=bucket_route_major(
            "PATCH",
            "/channels/{channel_id}",
            major_kind="channel",
            major_id=channel_id,
        ),
        serial_id=serial_channel(channel_id),
    )


def bucket_channel_delete(channel_id: int) -> BucketPair:
    return BucketPair(
        bucket_id=bucket_route_major(
            "DELETE",
            "/channels/{channel_id}",
            major_kind="channel",
            major_id=channel_id,
        ),
        serial_id=serial_channel(channel_id),
    )


# ===== Guild create channel (/guilds/{id}/channels) =====

def bucket_guild_create_channel(guild_id: int) -> BucketPair:
    return BucketPair(
        bucket_id=bucket_route_major(
            "POST",
            "/guilds/{guild_id}/channels",
            major_kind="guild",
            major_id=guild_id,
        ),
        serial_id=None,  # guild create は順序強制しなくても良い（欲しければ guild serial を追加してもOK）
    )


# ===== Threads (/channels/{id}/threads) =====

def bucket_channel_create_thread(channel_id: int) -> BucketPair:
    return BucketPair(
        bucket_id=bucket_route_major(
            "POST",
            "/channels/{channel_id}/threads",
            major_kind="channel",
            major_id=channel_id,
        ),
        serial_id=serial_channel(channel_id),
    )


# ===== Forum threads are same endpoint, but ok to share bucket with threads =====

def bucket_forum_create_thread(forum_channel_id: int) -> BucketPair:
    # 同じ /channels/{id}/threads なので同じbucketでOK
    return bucket_channel_create_thread(forum_channel_id)


# ===== Interaction webhooks =====

def bucket_webhook_followup(application_id: int, interaction_token: str) -> BucketPair:
    major = f"{application_id}:{interaction_token}"
    return BucketPair(
        bucket_id=bucket_route_major(
            "POST",
            "/webhooks/{application_id}/{interaction_token}",
            major_kind="webhook",
            major_id=major,
        ),
        serial_id=None,
    )


def bucket_webhook_edit_original(application_id: int, interaction_token: str) -> BucketPair:
    major = f"{application_id}:{interaction_token}"
    return BucketPair(
        bucket_id=bucket_route_major(
            "PATCH",
            "/webhooks/{application_id}/{interaction_token}/messages/@original",
            major_kind="webhook",
            major_id=major,
        ),
        serial_id=None,
    )

def bucket_webhook_delete_original(application_id: int, interaction_token: str) -> BucketPair:
    major = f"{application_id}:{interaction_token}"
    return BucketPair(
        bucket_id=bucket_route_major(
            "DELETE",
            "/webhooks/{application_id}/{interaction_token}/messages/@original",
            major_kind="webhook",
            major_id=major,
        ),
        serial_id=None,
    )

# ===== helpers =====

def try_channel_id(channel: Messageable) -> Optional[int]:
    return getattr(channel, "id", None)


def try_message_channel_id(message: Message) -> Optional[int]:
    ch = getattr(message, "channel", None)
    return getattr(ch, "id", None)
