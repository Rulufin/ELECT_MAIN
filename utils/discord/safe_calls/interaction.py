# utils/discord_tasks/interaction.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Union

import discord
from discord.utils import MISSING

logger = logging.getLogger(__name__)

from utils.discord.safe_calls.buckets import (
    bucket_webhook_followup,
    bucket_webhook_edit_original,
    bucket_webhook_delete_original,
)
from utils.discord.safe_calls.queued_call import queued_call
from utils.discord.safe_calls._missing import opt, opt_list


# view は三値で扱う:
# - MISSING: 引数未指定（触らない / send系では渡さない）
# - None   : 削除（edit系で components を消す）
# - View   : 置換/付与
#
# Pylance の reportInvalidTypeForm を避けるために type(MISSING) は使わない。
ViewParam = Union[discord.ui.View, None, object]


def _app_id(interaction: discord.Interaction) -> int:
    # 環境差フォールバック
    return int(interaction.application_id or interaction.client.application_id)


def _view_for_send(view: ViewParam):
    """send系: view=None は渡さない（MISSING）にして TypeError を防ぐ。"""
    if view is MISSING:
        return MISSING
    if view is None:
        return MISSING
    return view


def _view_for_edit(view: ViewParam):
    """edit系: view=None は「components削除」なのでそのまま通す。"""
    # MISSING は「触らない」なのでそのまま
    return view


# =========
# Defer
# =========

async def safe_defer(
    interaction: discord.Interaction,
    *,
    thinking: bool = False,
    ephemeral: bool = False,
) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer(thinking=thinking, ephemeral=ephemeral)
    except discord.NotFound:
        logger.warning("[safe_defer] interaction expired id=%s", interaction.id)
    except discord.HTTPException as e:
        logger.error("[safe_defer] failed id=%s status=%s text=%s", interaction.id, e.status, getattr(e, "text", ""))


# =========
# Delete original response (webhook)
# =========

async def safe_delete_original_response(
    interaction: discord.Interaction,
) -> None:
    """
    original response を削除する。

    - ephemeral を「確実に消せる」唯一の経路がこれ（@original）。
    - followup メッセージは original ではないので消えない。
    - webhook delete-original バケットで queue 管理する。
    """
    pair = bucket_webhook_delete_original(_app_id(interaction), interaction.token)

    async def _run() -> None:
        # discord.py のバージョン差吸収（基本はある）
        fn = getattr(interaction, "delete_original_response", None)
        if callable(fn):
            await fn()
            return

        # フォールバック（環境によっては存在しない）
        webhook = getattr(interaction, "followup", None)
        if webhook is not None:
            delete_message = getattr(webhook, "delete_message", None)
            if callable(delete_message):
                # ※discord.pyの実装差で通らない場合がある
                await delete_message("@original")
                return

        raise AttributeError("delete_original_response is not available in this discord.py environment")

    await queued_call(_run, bucket=pair, priority=0)


def _schedule_delete_original(
    interaction: discord.Interaction,
    *,
    delete_after: float,
) -> None:
    """
    edit_original_response で使う遅延削除。
    queue の worker をブロックしないため create_task で飛ばす。
    """
    async def _job():
        await asyncio.sleep(float(delete_after))
        await safe_delete_original_response(interaction)

    asyncio.create_task(_job())


# =========
# Send
# =========

async def safe_response_send(
    interaction: discord.Interaction,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    embeds: Optional[list[discord.Embed]] = None,
    view: ViewParam = MISSING,
    ephemeral: bool = False,
    delete_after: Optional[float] = None,
    suppress_embeds: bool = False,
) -> None:
    """
    まだ response が未完了なら response.send_message
    完了済みなら followup.send

    NOTE:
    - followup.send には delete_after を持たせない方針。
      （followup ephemeral は消せない & 誤用防止）
    - response.send_message の delete_after は discord.py が処理できるのでそのまま渡す。
    """
    if not interaction.response.is_done():
        try:
            await interaction.response.send_message(
                content=content,
                embed=opt(embed),
                embeds=opt_list(embeds),
                view=_view_for_send(view),
                ephemeral=ephemeral,
                delete_after=delete_after,
                suppress_embeds=suppress_embeds,
            )
        except discord.NotFound:
            logger.warning("[safe_response_send] interaction expired id=%s", interaction.id)
        except discord.HTTPException as e:
            logger.error("[safe_response_send] failed id=%s status=%s text=%s", interaction.id, e.status, getattr(e, "text", ""))
        return

    # followup 側へは delete_after を渡さない
    await safe_followup_send(
        interaction,
        content=content,
        embed=embed,
        embeds=embeds,
        view=view,
        ephemeral=ephemeral,
        suppress_embeds=suppress_embeds,
    )


async def safe_followup_send(
    interaction: discord.Interaction,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    embeds: Optional[list[discord.Embed]] = None,
    view: ViewParam = MISSING,
    ephemeral: bool = False,
    suppress_embeds: bool = False,
) -> discord.Message:
    """
    followup.send は webhook バケットで queue 管理

    NOTE:
    - delete_after は受け取らない（誤用防止）
    """
    pair = bucket_webhook_followup(_app_id(interaction), interaction.token)

    async def _run():
        return await interaction.followup.send(
            content=content,
            embed=opt(embed),
            embeds=opt_list(embeds),
            view=_view_for_send(view),
            ephemeral=ephemeral,
            suppress_embeds=suppress_embeds,
        )

    return await queued_call(_run, bucket=pair, priority=0)


# =========
# Edit original
# =========

async def safe_edit_original_response(
    interaction: discord.Interaction,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    embeds: Optional[list[discord.Embed]] = None,
    view: ViewParam = MISSING,
    delete_after: Optional[float] = None,
) -> discord.Message:
    """
    edit_original_response は webhook edit-original バケットで queue 管理

    - edit系では view=None が「components削除」なので、そのまま通す。
    - delete_after が指定された場合、original response を遅延削除する（@original）。
    """
    pair = bucket_webhook_edit_original(_app_id(interaction), interaction.token)

    async def _run():
        return await interaction.edit_original_response(
            content=content if content is not None else MISSING,
            embed=opt(embed),
            embeds=opt_list(embeds),
            view=_view_for_edit(view),
        )

    msg = await queued_call(_run, bucket=pair, priority=0)

    if delete_after is not None:
        _schedule_delete_original(interaction, delete_after=float(delete_after))

    return msg


# =========
# Edit (auto fallback)
# =========

async def safe_response_edit(
    interaction: discord.Interaction,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    embeds: Optional[list[discord.Embed]] = None,
    view: ViewParam = MISSING,
    suppress_embeds: bool = False,
) -> None:
    """
    まだ response が未完了なら interaction.response.edit_message()
    完了済みなら edit_original_response にフォールバック（= できる範囲で安全に編集）

    - response.edit_message: 元メッセージ(コンポーネント押下元)編集
    - edit_original_response: originalの編集（ephemeralの確実な編集先）
    """
    if not interaction.response.is_done():
        try:
            await interaction.response.edit_message(
                content=content if content is not None else MISSING,
                embed=opt(embed),
                embeds=opt_list(embeds),
                view=_view_for_edit(view),
                suppress_embeds=suppress_embeds,
            )
        except discord.NotFound:
            logger.warning("[safe_response_edit] interaction expired id=%s", interaction.id)
        except discord.HTTPException as e:
            logger.error("[safe_response_edit] failed id=%s status=%s text=%s", interaction.id, e.status, getattr(e, "text", ""))
        return

    await safe_edit_original_response(
        interaction,
        content=content,
        embed=embed,
        embeds=embeds,
        view=view,
    )
