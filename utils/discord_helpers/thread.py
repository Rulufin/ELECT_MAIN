from __future__ import annotations

from typing import Optional

import discord
from discord import ForumChannel, Thread


async def switch_thread_tag(
    thread: Optional[Thread],
    *,
    before_tag_id: Optional[int] = None,
    after_tag_id: Optional[int] = None,
    archived: bool = False,
) -> bool:
    """
    Forum Thread のタグを差し替える。

    Parameters
    ----------
    thread:
        対象の Thread
    before_tag_id:
        外したいタグID。None なら外さない
    after_tag_id:
        付けたいタグID。None なら付けない
    archived:
        True なら編集時に archive も行う

    Returns
    -------
    bool
        編集を実行できたら True、対象が不正などで何もしなければ False
    """
    if not isinstance(thread, Thread):
        return False

    new_tags = list(thread.applied_tags)

    if before_tag_id is not None:
        new_tags = [tag for tag in new_tags if tag.id != before_tag_id]

    if after_tag_id is not None and not any(tag.id == after_tag_id for tag in new_tags):
        forum = thread.parent
        if isinstance(forum, ForumChannel):
            after_tag = discord.utils.get(forum.available_tags, id=after_tag_id)
            if after_tag is not None:
                new_tags.append(after_tag)

    await thread.edit(applied_tags=new_tags, archived=archived)
    return True