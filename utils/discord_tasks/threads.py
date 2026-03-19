# utils/discord/threads.py
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Protocol, Sequence, cast

from discord import ForumChannel, TextChannel, Thread, Message
from discord.enums import ChannelType

from .safe_call import safe_call
from .errors import RateLimitInfo
from .buckets import (
    bucket_channel_create_thread,
    bucket_forum_create_thread,
    bucket_channel_patch,
    bucket_channel_delete,
)

RateLimitNotifier = Callable[[RateLimitInfo], Awaitable[None]]


# =========
# Typing (discord.py の ThreadWithMessage 吸収用)
# =========

class ThreadWithMessage(Protocol):
    thread: Thread
    message: Message


def _unwrap_thread(result: Any) -> Optional[Thread]:
    """
    discord.py の ForumChannel.create_thread は環境により
    - Thread
    - ThreadWithMessage (thread/message を持つオブジェクト)
    を返すことがあるので Thread に正規化する。
    """
    if result is None:
        return None

    if isinstance(result, Thread):
        return result

    t = getattr(result, "thread", None)
    if isinstance(t, Thread):
        return t

    return None


# =============================================================================
# TC Thread
# =============================================================================

async def safe_create_tc_thread(
    channel: TextChannel,
    *,
    name: str,
    auto_archive_duration: int = 1440,
    private: bool = False,
    invitable: bool = False,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> Optional[Thread]:
    """
    TextChannel 上のスレッド作成（public/private を統一）
    - private=False: public thread
    - private=True : private thread（invitable が有効）
    """
    bucket = bucket_channel_create_thread(channel.id)

    kwargs: dict[str, Any] = {
        "name": name,
        "auto_archive_duration": auto_archive_duration,
    }
    if private:
        kwargs["type"] = ChannelType.private_thread
        kwargs["invitable"] = invitable

    res = await safe_call(
        lambda: channel.create_thread(**kwargs, reason=reason),
        action="tc.create_thread",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )
    return cast(Optional[Thread], res)


async def safe_edit_tc_thread(
    thread: Thread,
    *,
    name: Optional[str] = None,
    archived: Optional[bool] = None,
    locked: Optional[bool] = None,
    auto_archive_duration: Optional[int] = None,
    reason: Optional[str] = None,
    use_queue: bool = True,
    on_rate_limit: Optional[RateLimitNotifier] = None,
    notify_threshold: float = 15.0,
) -> None:
    """
    TextChannel 起点の Thread を編集（Thread チャンネル PATCH）
    ※ archived はここで対応（別関数に分けない）
    """
    bucket = bucket_channel_patch(thread.id)

    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if archived is not None:
        kwargs["archived"] = archived
    if locked is not None:
        kwargs["locked"] = locked
    if auto_archive_duration is not None:
        kwargs["auto_archive_duration"] = auto_archive_duration

    if not kwargs:
        return

    await safe_call(
        lambda: thread.edit(**kwargs, reason=reason),
        action="tc.thread.edit",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
        route="PATCH /channels/{thread_id}",
        bucket_key=str(thread.id),
        on_rate_limit=on_rate_limit,
        notify_threshold=notify_threshold,
    )


async def safe_delete_tc_thread(
    thread: Thread,
    *,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> None:
    """
    TextChannel 起点の Thread を削除
    """
    bucket = bucket_channel_delete(thread.id)

    await safe_call(
        lambda: thread.delete(reason=reason),
        action="tc.thread.delete",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )


# =============================================================================
# Forum Thread (Post)
# =============================================================================

async def safe_create_forum_thread(
    forum: ForumChannel,
    *,
    name: str,
    content: str,
    auto_archive_duration: int = 1440,
    applied_tags: Optional[Sequence[int]] = None,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> Optional[Thread]:
    """
    ForumChannel.create_thread の safe。
    戻り値が ThreadWithMessage の場合があるため、常に Thread に正規化して返す。
    """
    bucket = bucket_forum_create_thread(forum.id)

    kwargs: dict[str, Any] = {
        "name": name,
        "content": content,
        "auto_archive_duration": auto_archive_duration,
    }
    if applied_tags:
        kwargs["applied_tags"] = list(applied_tags)

    res = await safe_call(
        lambda: forum.create_thread(**kwargs, reason=reason),
        action="forum.create_thread",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )

    return _unwrap_thread(res)


async def safe_edit_forum_thread(
    thread: Thread,
    *,
    name: Optional[str] = None,
    archived: Optional[bool] = None,
    locked: Optional[bool] = None,
    auto_archive_duration: Optional[int] = None,
    applied_tags: Optional[Sequence[int]] = None,
    reason: Optional[str] = None,
    use_queue: bool = True,
    on_rate_limit: Optional[RateLimitNotifier] = None,
    notify_threshold: float = 15.0,
) -> None:
    """
    Forum 起点の Thread を編集（Thread チャンネル PATCH + tags）
    - applied_tags: Forum のタグ更新（Thread.edit に流す）
    ※ Forum の「本文(content)」編集は Message.edit が別経路になるので、ここでは扱わない。
    """
    bucket = bucket_channel_patch(thread.id)

    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if archived is not None:
        kwargs["archived"] = archived
    if locked is not None:
        kwargs["locked"] = locked
    if auto_archive_duration is not None:
        kwargs["auto_archive_duration"] = auto_archive_duration
    if applied_tags is not None:
        kwargs["applied_tags"] = list(applied_tags)

    if not kwargs:
        return

    await safe_call(
        lambda: thread.edit(**kwargs, reason=reason),
        action="forum.thread.edit",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
        route="PATCH /channels/{thread_id}",
        bucket_key=str(thread.id),
        on_rate_limit=on_rate_limit,
        notify_threshold=notify_threshold,
    )


async def safe_delete_forum_thread(
    thread: Thread,
    *,
    reason: Optional[str] = None,
    use_queue: bool = True,
) -> None:
    """
    Forum 起点の Thread を削除（実体は Thread チャンネル削除）
    """
    bucket = bucket_channel_delete(thread.id)

    await safe_call(
        lambda: thread.delete(reason=reason),
        action="forum.thread.delete",
        bucket_id=bucket.bucket_id,
        serial_id=bucket.serial_id,
        use_queue=use_queue,
    )
