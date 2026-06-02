import logging
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

import discord
from discord import (
    Message, Guild, Member,
    ForumChannel, Thread, TextChannel,
    ForumTag
)

from services.judging.temp.ui.embeds import JT_Panel_Embed
from services.judging.temp.ui.views import JT_User_View, JT_Result_View

from utils.discord.helpers.resolve import resolve_member

from utils.ids import MAIN_CHANNELS, MAIN_ROLES, JUDGE_TAGS
from firestores.fs_judging_temp import FS_Judging_Temp
from firestores.fs_user_info import FS_Profile

logger = logging.getLogger(__name__)

FILENAME = "judging_temp_service"
TIMEZONE = ZoneInfo("Asia/Tokyo")


@dataclass(slots=True)
class TempJudgeCreateResult:
    user_thread: Thread
    admin_thread: Thread
    user_message: Message
    date_ymd: str
    profile_url: str
    tag_ids: list[int]


class TempJudgingService:
    def __init__(self):
        self.fs_judging = FS_Judging_Temp()
        self.fs_profile = FS_Profile()

    def _build_tag_ids_and_profile_channel_id(
        self,
        member: Member,
    ) -> tuple[list[int], int | None]:
        role_ids_now = {role.id for role in member.roles}

        has_g_male = MAIN_ROLES.P_MALE in role_ids_now
        has_g_female = MAIN_ROLES.P_FEMALE in role_ids_now

        tag_ids = [JUDGE_TAGS.TEMP_NOW]
        profile_ch_id = None

        if has_g_male and not has_g_female:
            tag_ids.append(JUDGE_TAGS.TEMP_MALE)
            profile_ch_id = MAIN_CHANNELS.PROFILE_MALE

        elif has_g_female and not has_g_male:
            tag_ids.append(JUDGE_TAGS.TEMP_FEMALE)
            profile_ch_id = MAIN_CHANNELS.PROFILE_FEMALE

        else:
            logger.warning(
                "[%s] gender role ambiguous: male=%s female=%s user=%s",
                FILENAME,
                has_g_male,
                has_g_female,
                member.id,
            )

        return tag_ids, profile_ch_id

    async def _get_profile_message_id(self, member: Member) -> int:
        profile_data = await self.fs_profile.get_profile_data(author_id=member.id)
        if not profile_data:
            raise RuntimeError("プロフィールデータが見つかりませんでした。")

        profile_id = profile_data.get("MESSAGE_ID")
        if not profile_id:
            raise RuntimeError("プロフィールメッセージIDが見つかりませんでした。")

        return int(profile_id)

    def _build_profile_url(
        self,
        guild: Guild,
        profile_channel_id: int,
        profile_message_id: int,
    ) -> str:
        return (
            f"https://discord.com/channels/"
            f"{guild.id}/{profile_channel_id}/{profile_message_id}"
        )

    def _build_applied_tags(
        self,
        forum: ForumChannel,
        tag_ids: list[int],
    ) -> list[ForumTag]:
        applied_tags: list[ForumTag] = []

        for tag_id in dict.fromkeys(tag_ids):
            tag = forum.get_tag(tag_id)
            if tag is None:
                logger.warning(
                    "[%s] forum tag not found: forum_id=%s tag_id=%s",
                    FILENAME,
                    forum.id,
                    tag_id,
                )
                continue

            applied_tags.append(tag)

        return applied_tags

    async def _resolve_created_thread_and_message(
        self,
        created: Any,
    ) -> tuple[Thread, Message | None]:
        if isinstance(created, Thread):
            thread = created
            starter_message = None
        else:
            thread = created.thread
            starter_message = getattr(created, "message", None)

        if starter_message is None:
            try:
                starter_message = await thread.fetch_message(thread.id)
            except Exception:
                logger.warning(
                    "[%s] failed to fetch starter message: thread_id=%s",
                    FILENAME,
                    thread.id,
                    exc_info=True,
                )
                starter_message = None

        return thread, starter_message

    def _resolve_date_ymd_from_message(
        self,
        legacy_message: Message,
    ) -> str | None:
        created_at = getattr(legacy_message, "created_at", None)
        if created_at is None:
            return None

        return created_at.astimezone(TIMEZONE).strftime("%Y%m%d")

    async def create_temp_judge_panel(
        self,
        *,
        guild: Guild,
        member: Member,
        user_forum: ForumChannel,
        admin_forum: ForumChannel,
    ) -> TempJudgeCreateResult:
        now_jst = datetime.now(TIMEZONE)
        date_ymd = now_jst.strftime("%Y%m%d")

        tag_ids, profile_ch_id = self._build_tag_ids_and_profile_channel_id(member)
        if profile_ch_id is None:
            raise RuntimeError(
                "性別ロールの判定ができなかったため、プロフィールURLを作成できませんでした。"
            )

        profile_message_id = await self._get_profile_message_id(member)
        profile_url = self._build_profile_url(
            guild=guild,
            profile_channel_id=profile_ch_id,
            profile_message_id=profile_message_id,
        )

        embed = JT_Panel_Embed(user=member, profile_url=profile_url, date_ymd=date_ymd)

        user_created = await user_forum.create_thread(
            name=f"{member.id}-{date_ymd}",
            content=f"{member.display_name}({member.mention})",
            embed=embed,
            view=JT_User_View(),
            applied_tags=self._build_applied_tags(user_forum, tag_ids),
        )
        user_thread, user_message = await self._resolve_created_thread_and_message(user_created)

        admin_created = await admin_forum.create_thread(
            name=f"{member.id}-{date_ymd}",
            content=f"{member.display_name}({member.mention})",
            embed=embed,
            view=JT_Result_View(),
            applied_tags=self._build_applied_tags(admin_forum, tag_ids),
        )
        admin_thread, _ = await self._resolve_created_thread_and_message(admin_created)

        if user_message is None:
            raise RuntimeError("メンバー用仮免審査スレッドの開始メッセージを取得できませんでした。")

        await self.fs_judging.init_day_entry(
            target_id=member.id,
            message_id=user_message.id,
            date_ymd=date_ymd,
            admin_thread_id=admin_thread.id,
            user_thread_id=user_thread.id,
        )

        return TempJudgeCreateResult(
            user_thread=user_thread,
            admin_thread=admin_thread,
            user_message=user_message,
            date_ymd=date_ymd,
            profile_url=profile_url,
            tag_ids=tag_ids,
        )

    async def migrate_legacy_user_panel(
        self,
        *,
        guild: Guild,
        legacy_message: Message,
        user_forum: ForumChannel,
        date_ymd: str | None = None,
        delete_old_entry: bool = True,
        disable_legacy_view: bool = True,
    ) -> str:
        if not legacy_message.embeds:
            return "embed_not_found"

        embed = legacy_message.embeds[0]
        author_url = getattr(embed.author, "url", None)

        if not author_url:
            return "author_url_not_found"

        match = re.search(r"(\d{15,25})", author_url)
        if not match:
            return "target_id_not_found"

        target_id = int(match.group(1))

        resolved_date_ymd = date_ymd or self._resolve_date_ymd_from_message(legacy_message)
        if not resolved_date_ymd:
            return "date_ymd_not_found"

        entry = await self.fs_judging.get_entry(
            target_id=target_id,
            message_id=legacy_message.id,
            date_ymd=resolved_date_ymd,
        )

        source_date_ymd = resolved_date_ymd

        if not entry:
            entry = await self.fs_judging.get_entry(
                target_id=target_id,
                message_id=legacy_message.id,
                date_ymd="None",
            )
            if entry:
                source_date_ymd = "None"

        if not entry:
            return "entry_not_found"

        old_user_message_id = entry.get("user_message_id")
        old_user_thread_id = entry.get("user_thread_id")

        if old_user_thread_id and old_user_message_id:
            return "already_migrated"

        thread_name = f"{target_id}-{resolved_date_ymd}"

        target = await resolve_member(guild=guild, user_id=target_id)

        created = await user_forum.create_thread(
            name=thread_name,
            content=f"{target.display_name} ({target.mention})",
            embed=embed,
            view=JT_User_View(),
        )
        user_thread, user_message = await self._resolve_created_thread_and_message(created)

        if user_message is None:
            return "user_message_not_found"

        migrate_result = await self.fs_judging.migrate_message_entry(
            target_id=target_id,
            old_message_id=legacy_message.id,
            new_message_id=user_message.id,
            date_ymd=resolved_date_ymd,
            old_date_ymd=source_date_ymd,
            user_thread_id=user_thread.id,
            user_message_id=user_message.id,
            delete_old=delete_old_entry,
        )
        if migrate_result != "migrated":
            return migrate_result

        if disable_legacy_view:
            try:
                await legacy_message.edit(
                    content="この仮免審査パネルは新しいフォーラムへ移行済みです。",
                    view=None,
                )
            except Exception:
                logger.warning(
                    "[%s] failed to disable legacy view message_id=%s",
                    FILENAME,
                    legacy_message.id,
                    exc_info=True,
                )

        return "migrated"

    async def migrate_legacy_user_panels_in_text_channel(
        self,
        *,
        guild: Guild,
        legacy_text_channel: TextChannel,
        user_forum: ForumChannel,
        limit: int | None = None,
    ) -> dict[str, int]:
        results = {
            "migrated": 0,
            "already_migrated": 0,
            "entry_not_found": 0,
            "embed_not_found": 0,
            "author_url_not_found": 0,
            "date_ymd_not_found": 0,
            "target_id_not_found": 0,
            "user_message_not_found": 0,
            "same_message_id": 0,
            "error_occurred": 0,
            "other": 0,
        }

        count = 0
        bot_member = guild.me
        if bot_member is None:
            me = getattr(guild, "me", None)
            if me is not None:
                bot_member = me

        async for message in legacy_text_channel.history(limit=None, oldest_first=True):
            if limit is not None and count >= limit:
                break

            if bot_member is not None and message.author.id != bot_member.id:
                continue

            if not message.embeds:
                continue

            try:
                resolved_date_ymd = self._resolve_date_ymd_from_message(message)
                if not resolved_date_ymd:
                    result = "date_ymd_not_found"
                else:
                    result = await self.migrate_legacy_user_panel(
                        guild=guild,
                        legacy_message=message,
                        user_forum=user_forum,
                        date_ymd=resolved_date_ymd,
                    )
            except Exception:
                logger.exception(
                    "[%s] bulk migrate failed message_id=%s",
                    FILENAME,
                    message.id,
                )
                result = "error_occurred"

            if result in results:
                results[result] += 1
            else:
                results["other"] += 1

            count += 1

        return results
    
    async def repair_none_date_from_legacy_message(
        self,
        *,
        legacy_message: Message,
        delete_old: bool = True,
    ) -> str:
        if not legacy_message.embeds:
            return "embed_not_found"

        embed = legacy_message.embeds[0]
        author_url = getattr(embed.author, "url", None)

        if not author_url:
            return "author_url_not_found"

        match = re.search(r"(\d{15,25})", author_url)
        if not match:
            return "target_id_not_found"

        target_id = int(match.group(1))

        correct_date_ymd = self._resolve_date_ymd_from_message(legacy_message)
        if not correct_date_ymd:
            return "date_ymd_not_found"

        none_entry = await self.fs_judging.get_entry(
            target_id=target_id,
            message_id=legacy_message.id,
            date_ymd="None",
        )
        if not none_entry:
            existing_entry = await self.fs_judging.get_entry(
                target_id=target_id,
                message_id=legacy_message.id,
                date_ymd=correct_date_ymd,
            )
            if existing_entry:
                return "already_repaired"
            return "not_found"

        result = await self.fs_judging.repair_none_date_entry(
            target_id=target_id,
            message_id=legacy_message.id,
            correct_date_ymd=correct_date_ymd,
            delete_old=delete_old,
        )
        return result

    async def repair_none_date_entries_in_text_channel(
        self,
        *,
        guild: Guild,
        legacy_text_channel: TextChannel,
        limit: int | None = None,
        only_bot_messages: bool = True,
    ) -> dict[str, int]:
        results = {
            "migrated": 0,
            "already_repaired": 0,
            "not_found": 0,
            "embed_not_found": 0,
            "author_url_not_found": 0,
            "target_id_not_found": 0,
            "date_ymd_not_found": 0,
            "invalid_date_ymd": 0,
            "error_occurred": 0,
            "other": 0,
        }

        count = 0
        bot_member = guild.me

        async for message in legacy_text_channel.history(limit=None, oldest_first=True):
            if limit is not None and count >= limit:
                break

            if only_bot_messages and bot_member is not None and message.author.id != bot_member.id:
                continue

            if not message.embeds:
                continue

            try:
                result = await self.repair_none_date_from_legacy_message(
                    legacy_message=message,
                    delete_old=True,
                )
            except Exception:
                logger.exception(
                    "[%s] bulk none-date repair failed message_id=%s",
                    FILENAME,
                    message.id,
                )
                result = "error_occurred"

            if result in results:
                results[result] += 1
            else:
                results["other"] += 1

            count += 1

        return results
    
    async def recreate_user_panel_from_firestore(
        self,
        *,
        guild: Guild,
        target_id: int,
        old_message_id: int,
        user_forum: ForumChannel,
        archive_old_thread: bool = False,
    ) -> str:
        entry = await self.fs_judging.find_entry_by_message_id(
            target_id=target_id,
            message_id=old_message_id,
        )
        if not entry:
            return "entry_not_found"

        date_ymd = str(entry.get("date_ymd") or "").strip()
        if not date_ymd or date_ymd == "None":
            return "date_ymd_not_found"

        try:
            member = guild.get_member(target_id) or await guild.fetch_member(target_id)
        except Exception:
            member = None

        if member is None:
            return "member_not_found"

        tag_ids, profile_ch_id = self._build_tag_ids_and_profile_channel_id(member)
        if profile_ch_id is None:
            return "profile_channel_not_found"

        try:
            profile_message_id = await self._get_profile_message_id(member)
        except Exception:
            return "profile_message_not_found"

        profile_url = self._build_profile_url(
            guild=guild,
            profile_channel_id=profile_ch_id,
            profile_message_id=profile_message_id,
        )

        embed = JT_Panel_Embed(
            user=member,
            profile_url=profile_url,
            date_ymd=date_ymd,
        )

        created = await user_forum.create_thread(
            name=f"{target_id}-{date_ymd}",
            content=f"{member.display_name} ({member.mention})",
            embed=embed,
            view=JT_User_View(),
            applied_tags=self._build_applied_tags(user_forum, tag_ids),
        )
        user_thread, user_message = await self._resolve_created_thread_and_message(created)

        if user_message is None:
            return "user_message_not_found"

        migrate_result = await self.fs_judging.migrate_message_entry(
            target_id=target_id,
            old_message_id=old_message_id,
            new_message_id=user_message.id,
            date_ymd=date_ymd,
            old_date_ymd=date_ymd,
            user_thread_id=user_thread.id,
            user_message_id=user_message.id,
            delete_old=True,
        )
        if migrate_result != "migrated":
            return migrate_result

        old_user_thread_id = entry.get("user_thread_id")
        if archive_old_thread and old_user_thread_id:
            try:
                old_thread = guild.get_thread(int(old_user_thread_id)) or await guild.fetch_channel(int(old_user_thread_id))
                if isinstance(old_thread, Thread):
                    await old_thread.edit(archived=True, locked=False)
            except Exception:
                logger.warning(
                    "[%s] failed to archive old thread thread_id=%s",
                    FILENAME,
                    old_user_thread_id,
                    exc_info=True,
                )

        return "migrated"