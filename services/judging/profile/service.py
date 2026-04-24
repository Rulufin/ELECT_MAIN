from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import ForumChannel, Guild, Message

from firestores.fs_judging import FS_Judging
from services.judging.profile.configs import PROFILE_JUDGING_CONFIG
from services.judging.profile.ui.embeds import (
    Judging_Entry_Embed,
    Judging_Profile_Embed,
)
from services.judging.profile.ui.views import (
    Judging_Panel_View,
    Judging_Result_View,
)

logger = logging.getLogger(__name__)

FILENAME = "profile_judging_service"
TIMEZONE = ZoneInfo("Asia/Tokyo")


class ProfileJudgingService:
    def __init__(self) -> None:
        self.fs_judging = FS_Judging()
        self.config = PROFILE_JUDGING_CONFIG

    async def start_from_reaction(self, guild: Guild, message: Message) -> None:
        author = message.author
        formatted_date = self._format_message_date(message)

        judge_forum = await self._fetch_result_forum(guild)
        if judge_forum is None:
            return

        judge_channel = await self._fetch_judge_channel(guild)
        if judge_channel is None:
            return

        profile_embed = Judging_Profile_Embed(
            author=author,
            message=message,
            formatted_date=formatted_date,
        )
        panel_view = Judging_Panel_View()

        judge_message = await judge_channel.send(
            content=self._build_mention_text(),
            embed=profile_embed,
            view=panel_view,
        )

        result_view = Judging_Result_View()
        thread_name = f"{author.id}-{formatted_date}"
        applied_tags = self._resolve_forum_tags(judge_forum=judge_forum, message=message)

        created = await judge_forum.create_thread(
            name=thread_name,
            content=f"{author.display_name}({author.mention})",
            embed=profile_embed,
            view=result_view,
            applied_tags=applied_tags,
        )

        if isinstance(created, discord.Thread):
            thread = created
        else:
            thread = created.thread

        await self.fs_judging.init_day_entry(
            target_id=author.id,
            message_id=judge_message.id,
            date_ymd=formatted_date,
            thread_id=thread.id,
        )

        await self._send_entry_dm(author)

    async def _fetch_result_forum(self, guild: Guild) -> ForumChannel | None:
        forum_id = self.config.channels.result_forum_id
        channel = guild.get_channel(forum_id) or await guild.fetch_channel(forum_id)

        if not isinstance(channel, ForumChannel):
            logger.error(
                "[%s] result forum is not ForumChannel (id=%s)",
                FILENAME,
                forum_id,
            )
            return None

        return channel

    async def _fetch_judge_channel(self, guild: Guild):
        channel_id = self.config.channels.judge_channel_id
        channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)

        if channel is None:
            logger.error(
                "[%s] judge channel not found (id=%s)",
                FILENAME,
                channel_id,
            )
            return None

        return channel

    def _format_message_date(self, message: Message) -> str:
        created_at_jst = message.created_at.astimezone(TIMEZONE)
        return created_at_jst.strftime("%Y%m%d")

    def _build_mention_text(self) -> str:
        mention_roles = self.config.mention_roles
        return f"<@&{mention_roles.member_role_id}> <@&{mention_roles.probation_member_role_id}>"

    def _resolve_forum_tags(self, *, judge_forum: ForumChannel, message: Message) -> list:
        author = message.author
        role_ids_now = {r.id for r in getattr(author, "roles", [])}

        gender_roles = self.config.gender_roles
        tags = self.config.tags

        has_male = gender_roles.male_role_id in role_ids_now
        has_female = gender_roles.female_role_id in role_ids_now

        tag_ids: list[int] = [tags.now_tag_id]

        if has_male and not has_female:
            tag_ids.append(tags.male_tag_id)
        elif has_female and not has_male:
            tag_ids.append(tags.female_tag_id)
        else:
            logger.warning(
                "[%s] gender role ambiguous: male=%s female=%s user=%s",
                FILENAME,
                has_male,
                has_female,
                author.id,
            )

        applied_tags = []
        for tag_id in dict.fromkeys(tag_ids):
            tag_obj = judge_forum.get_tag(tag_id)
            if tag_obj is not None:
                applied_tags.append(tag_obj)
            else:
                logger.warning(
                    "[%s] ForumTag not found (forum_id=%s, tag_id=%s)",
                    FILENAME,
                    judge_forum.id,
                    tag_id,
                )

        return applied_tags

    async def _send_entry_dm(self, author) -> None:
        try:
            await author.send(embed=Judging_Entry_Embed())
        except Exception as e:
            logger.error(
                "[%s] failed to send judging entry DM to user=%s: %s",
                FILENAME,
                getattr(author, "id", "unknown"),
                str(e),
                exc_info=True,
            )