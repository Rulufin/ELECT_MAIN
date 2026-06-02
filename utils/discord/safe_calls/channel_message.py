# utils/discord_tasks/channel_message.py
from __future__ import annotations

from typing import Optional, Union

import discord
from discord.utils import MISSING
from discord import (
    Embed, Message, 
)
from discord.ui import View

from utils.discord.safe_calls.buckets import (
    bucket_channel_send,
    bucket_message_edit,
    bucket_message_delete,
    try_channel_id,
    try_message_channel_id,
)
from utils.discord.safe_calls.queued_call import queued_call
from utils.discord.safe_calls._missing import opt, opt_list

ViewParam = Union[discord.ui.View, None, object]  # object = MISSING用

def _view_for_edit(view: ViewParam):
    # MISSING: 触らない
    # None: components削除
    return view

async def safe_channel_send(
    channel: discord.abc.Messageable,
    *,
    content: Optional[str] = None,
    embed: Optional[Embed] = None,
    embeds: Optional[list[Embed]] = None,
    view: Optional[View] = None,
    delete_after: Optional[float] = None,
) -> Message:
    ch_id = try_channel_id(channel)
    if ch_id is None:
        # DM などで id が取れないパターンは素直に直呼び（bucket不要）
        return await channel.send(
            content=content,
            embed=opt(embed),
            embeds=opt_list(embeds),
            view=opt(view),
            delete_after=delete_after,
        )

    pair = bucket_channel_send(ch_id)

    async def _run():
        return await channel.send(
            content=content,
            embed=opt(embed),
            embeds=opt_list(embeds),
            view=opt(view),
            delete_after=delete_after,
        )

    return await queued_call(_run, bucket=pair)


async def safe_message_edit(
    message: discord.Message,
    *,
    content: Optional[str] = None,
    embed: Optional[Embed] = None,
    embeds: Optional[list[Embed]] = None,
    view: ViewParam = MISSING,
) -> discord.Message:
    ch_id = try_message_channel_id(message)
    if ch_id is None:
        return await message.edit(
            content=content if content is not None else MISSING,
            embed=opt(embed),
            embeds=opt_list(embeds),
            view=_view_for_edit(view),
        )

    pair = bucket_message_edit(ch_id, message.id)

    async def _run():
        return await message.edit(
            content=content if content is not None else MISSING,
            embed=opt(embed),
            embeds=opt_list(embeds),
            view=_view_for_edit(view),
        )

    return await queued_call(_run, bucket=pair)

async def safe_message_delete(
    message: Message,
    *,
    delay: Optional[float] = None,
) -> None:
    """
    message.delete() を bucket + queue 管理で安全に実行する。

    - delay は discord.py の delete(delay=...) に合わせたオプション
    - 基本は message.channel.id が取れるので bucket 化できる
    """
    ch_id = try_message_channel_id(message)
    if ch_id is None:
        # ほぼ無いが、念のためフォールバック
        await message.delete(delay=delay)
        return

    pair = bucket_message_delete(ch_id, message.id)

    async def _run():
        await message.delete(delay=delay)

    await queued_call(_run, bucket=pair)
