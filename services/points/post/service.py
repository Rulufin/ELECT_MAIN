from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import Message

from configs.google_setup import client
from firestores.fs_points import FS_Points
from services.points.post.configs import POST_POINT_RULES, PostPointRule
from google.cloud.firestore_v1.base_query import FieldFilter

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Tokyo")
FILENAME = "post_point_service"

INDEX_COLLECTION = "PointMessageIndex"


class PostPointService:
    def __init__(self, fs_points: FS_Points | None = None):
        self.fs_points = fs_points or FS_Points()
        self.db = client.firestore_db

    def get_rule_by_channel_id(self, channel_id: int) -> PostPointRule | None:
        return POST_POINT_RULES.get(int(channel_id))

    def get_rule(self, message: Message) -> PostPointRule | None:
        if message.guild is None:
            return None

        if message.author.bot:
            return None

        return self.get_rule_by_channel_id(message.channel.id)

    async def grant_post_points(self, message: Message) -> None:
        rule = self.get_rule(message)
        if rule is None:
            return

        now = datetime.now(TIMEZONE)
        event_id = f"post_{message.id}"

        await self.fs_points.record_event(
            user_id=message.author.id,
            event_id=event_id,
            event_type=rule.event_type,
            genre=rule.genre,
            delta=rule.point,
            note=rule.note,
            ts=now,
            meta={
                "message_id": message.id,
                "channel_id": message.channel.id,
                "guild_id": message.guild.id if message.guild else None,
                "point": rule.point,
                "action": "create",
            },
        )

        await self._save_message_index(
            message=message,
            rule=rule,
            created_event_id=event_id,
        )

    async def revoke_post_points_raw(
        self,
        *,
        guild_id: int | None,
        channel_id: int,
        message_id: int,
    ) -> None:
        rule = self.get_rule_by_channel_id(channel_id)
        if rule is None:
            return

        index = await self._get_message_index(message_id)
        if not index:
            return

        user_id = index.get("user_id")
        if user_id is None:
            return

        point = int(index.get("point", rule.point) or rule.point)

        now = datetime.now(TIMEZONE)

        await self.fs_points.record_event(
            user_id=int(user_id),
            event_id=f"delete_{message_id}",
            event_type=rule.event_type,
            genre=rule.genre,
            delta=-point,
            note=f"{rule.note} 削除",
            ts=now,
            meta={
                "message_id": message_id,
                "channel_id": channel_id,
                "guild_id": guild_id,
                "point": point,
                "action": "delete",
                "created_event_id": index.get("created_event_id"),
            },
        )

        await self._mark_message_deleted(message_id)

    async def _save_message_index(
        self,
        *,
        message: Message,
        rule: PostPointRule,
        created_event_id: str,
    ) -> None:
        doc_ref = self.db.collection(INDEX_COLLECTION).document(str(message.id))

        await doc_ref.set(
            {
                "message_id": message.id,
                "user_id": message.author.id,
                "channel_id": message.channel.id,
                "guild_id": message.guild.id if message.guild else None,
                "point": rule.point,
                "event_type": str(rule.event_type),
                "genre": str(rule.genre),
                "note": rule.note,
                "created_event_id": created_event_id,
                "deleted": False,
                "created_at": datetime.now(TIMEZONE),
            },
            merge=True,
        )

    async def _get_message_index(self, message_id: int) -> dict | None:
        doc_ref = self.db.collection(INDEX_COLLECTION).document(str(message_id))
        snap = await doc_ref.get()

        if not snap.exists:
            return None

        return snap.to_dict() or {}

    async def cleanup_by_channel_ids(self, channel_ids: list[int]) -> dict[int, int]:
        """
        指定チャンネルで付与されたイベントと PointMessageIndex を完全削除し、
        影響ユーザーの totals を再計算する。
        戻り値: {user_id: 削除件数}
        """
        affected: dict[int, int] = {}

        for channel_id in channel_ids:
            q = self.db.collection(INDEX_COLLECTION).where(
                filter=FieldFilter("channel_id", "==", channel_id)
            )
            async for snap in q.stream():
                data = snap.to_dict() or {}
                user_id = data.get("user_id")
                event_id = data.get("created_event_id")

                if user_id is not None and event_id:
                    uid = int(user_id)
                    await self.fs_points.delete_event(uid, str(event_id))
                    affected[uid] = affected.get(uid, 0) + 1

                await snap.reference.delete()

        for uid in affected:
            await self.fs_points.recalc_user_totals(uid)

        return affected

    async def _mark_message_deleted(self, message_id: int) -> None:
        doc_ref = self.db.collection(INDEX_COLLECTION).document(str(message_id))

        await doc_ref.set(
            {
                "deleted": True,
                "deleted_at": datetime.now(TIMEZONE),
            },
            merge=True,
        )