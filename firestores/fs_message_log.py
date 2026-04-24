from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import discord

from zoneinfo import ZoneInfo

from google.cloud.firestore_v1 import AsyncClient
from google.cloud import firestore_v1 as firestore
from google.api_core.datetime_helpers import DatetimeWithNanoseconds

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateTimeLike = Union[datetime, DatetimeWithNanoseconds]


class FS_Message_Log:
    """
    メッセージ単位の判定ログ。

    Firestore 構造:
    MessageLog/{message_id}
      message_id: int
      guild_id: int | None
      channel_id: int
      user_id: int
      content: str
      has_image: bool
      image_count: int

      attachments: [
        {
          id: int | None,
          filename: str,
          content_type: str | None,
          size: int | None,
          url: str | None,
          proxy_url: str | None,
          is_image: bool,
        },
        ...
      ]

      awarded: bool
      point_delta: int
      point_event_id: str | None

      deleted: bool
      deleted_at: Timestamp | None

      reverted: bool
      reverted_at: Timestamp | None
      revert_event_id: str | None

      created_at: Timestamp
      updated_at: Timestamp
    """

    ROOT_COLLECTION = "MessageLog"
    TZ_JST = ZoneInfo("Asia/Tokyo")
    IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

    def __init__(
        self,
        root_collection: str = ROOT_COLLECTION,
        queue_manager=firestore_queue,
    ) -> None:
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")

        self.db: AsyncClient = client.firestore_db
        self.root = root_collection
        self.queue = queue_manager

    # ─────────────────────────
    # Firestore refs / queue wrappers
    # ─────────────────────────

    def _doc(self, message_id: IntStr):
        return self.db.collection(self.root).document(str(message_id))

    async def _q(self, fn):
        try:
            return await self.queue.enqueue(fn)
        except Exception as e:
            logger.error(f"[FS_Message_Log] queue error: {e}", exc_info=True)
            return None

    async def _q_get(self, doc_ref):
        async def _op():
            return await doc_ref.get()

        return await self._q(_op)

    async def _q_set(self, doc_ref, data: Dict[str, Any], *, merge: bool = True):
        async def _op():
            return await doc_ref.set(data, merge=merge)

        return await self._q(_op)

    async def _q_update(self, doc_ref, data: Dict[str, Any]):
        async def _op():
            return await doc_ref.update(data)

        return await self._q(_op)

    async def _q_delete(self, doc_ref):
        async def _op():
            return await doc_ref.delete()

        return await self._q(_op)

    # ─────────────────────────
    # datetime helpers
    # ─────────────────────────

    @classmethod
    def _now(cls) -> datetime:
        return datetime.now(cls.TZ_JST)

    # ─────────────────────────
    # attachment helpers
    # ─────────────────────────

    @classmethod
    def is_image_attachment(cls, attachment: discord.Attachment) -> bool:
        content_type = getattr(attachment, "content_type", None)
        if content_type and str(content_type).startswith("image/"):
            return True

        filename = str(getattr(attachment, "filename", "") or "").lower()
        return filename.endswith(cls.IMAGE_EXTENSIONS)

    @classmethod
    def serialize_attachment(cls, attachment: discord.Attachment) -> Dict[str, Any]:
        return {
            "id": int(attachment.id) if getattr(attachment, "id", None) is not None else None,
            "filename": str(getattr(attachment, "filename", "") or ""),
            "content_type": getattr(attachment, "content_type", None),
            "size": int(attachment.size) if getattr(attachment, "size", None) is not None else None,
            "url": str(getattr(attachment, "url", "") or "") or None,
            "proxy_url": str(getattr(attachment, "proxy_url", "") or "") or None,
            "is_image": cls.is_image_attachment(attachment),
        }

    @classmethod
    def serialize_attachments(cls, attachments: List[discord.Attachment]) -> List[Dict[str, Any]]:
        return [cls.serialize_attachment(a) for a in attachments]

    @classmethod
    def count_images_from_payload(cls, attachments: List[Dict[str, Any]]) -> int:
        return sum(1 for a in attachments if bool(a.get("is_image")))

    # ─────────────────────────
    # basic getters
    # ─────────────────────────

    async def get_log(self, message_id: IntStr) -> Dict[str, Any]:
        snap = await self._q_get(self._doc(message_id))
        if not snap or not snap.exists:
            return {}
        return snap.to_dict() or {}

    async def exists(self, message_id: IntStr) -> bool:
        snap = await self._q_get(self._doc(message_id))
        return bool(snap and snap.exists)

    # ─────────────────────────
    # create / upsert
    # ─────────────────────────

    async def upsert_from_message(
        self,
        message: discord.Message,
        *,
        attachments: Optional[List[discord.Attachment]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        discord.Message からログを作成 / 更新する。
        投稿時 on_message でも、必要なら on_message_edit でも使える。
        """
        now = self._now()
        target_attachments = attachments if attachments is not None else list(message.attachments)
        serialized = self.serialize_attachments(target_attachments)
        image_count = self.count_images_from_payload(serialized)

        data: Dict[str, Any] = {
            "message_id": int(message.id),
            "guild_id": int(message.guild.id) if message.guild else None,
            "channel_id": int(message.channel.id),
            "user_id": int(message.author.id),
            "content": str(message.content or ""),
            "has_image": image_count > 0,
            "image_count": int(image_count),
            "attachments": serialized,
            "updated_at": now,
        }

        snap = await self._q_get(self._doc(message.id))
        if not snap or not snap.exists:
            data.update({
                "awarded": False,
                "point_delta": 0,
                "point_event_id": None,
                "deleted": False,
                "deleted_at": None,
                "reverted": False,
                "reverted_at": None,
                "revert_event_id": None,
                "created_at": now,
            })

        if extra:
            data.update(extra)

        await self._q_set(self._doc(message.id), data, merge=True)

    async def create_log(
        self,
        *,
        message_id: IntStr,
        guild_id: Optional[IntStr],
        channel_id: IntStr,
        user_id: IntStr,
        content: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None,
        has_image: Optional[bool] = None,
        image_count: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        discord.Message を使わずに直接作成したい場合用。
        """
        now = self._now()
        payload_attachments = list(attachments or [])

        if has_image is None:
            has_image = any(bool(a.get("is_image")) for a in payload_attachments)

        if image_count is None:
            image_count = sum(1 for a in payload_attachments if bool(a.get("is_image")))

        data: Dict[str, Any] = {
            "message_id": int(message_id),
            "guild_id": int(guild_id) if guild_id is not None else None,
            "channel_id": int(channel_id),
            "user_id": int(user_id),
            "content": str(content or ""),
            "attachments": payload_attachments,
            "has_image": bool(has_image),
            "image_count": int(image_count),
            "awarded": False,
            "point_delta": 0,
            "point_event_id": None,
            "deleted": False,
            "deleted_at": None,
            "reverted": False,
            "reverted_at": None,
            "revert_event_id": None,
            "created_at": now,
            "updated_at": now,
        }

        if extra:
            data.update(extra)

        await self._q_set(self._doc(message_id), data, merge=False)

    # ─────────────────────────
    # award / delete / revert
    # ─────────────────────────

    async def mark_awarded(
        self,
        message_id: IntStr,
        *,
        point_delta: int,
        point_event_id: Optional[str] = None,
    ) -> None:
        now = self._now()
        await self._q_set(
            self._doc(message_id),
            {
                "awarded": True,
                "point_delta": int(point_delta),
                "point_event_id": point_event_id,
                "updated_at": now,
            },
            merge=True,
        )

    async def clear_awarded(self, message_id: IntStr) -> None:
        now = self._now()
        await self._q_set(
            self._doc(message_id),
            {
                "awarded": False,
                "point_delta": 0,
                "point_event_id": None,
                "updated_at": now,
            },
            merge=True,
        )

    async def mark_deleted(self, message_id: IntStr) -> None:
        now = self._now()
        await self._q_set(
            self._doc(message_id),
            {
                "deleted": True,
                "deleted_at": now,
                "updated_at": now,
            },
            merge=True,
        )

    async def mark_restored(self, message_id: IntStr) -> None:
        """
        必要なら復元用。
        """
        now = self._now()
        await self._q_set(
            self._doc(message_id),
            {
                "deleted": False,
                "deleted_at": None,
                "updated_at": now,
            },
            merge=True,
        )

    async def mark_reverted(
        self,
        message_id: IntStr,
        *,
        revert_event_id: Optional[str] = None,
    ) -> None:
        now = self._now()
        await self._q_set(
            self._doc(message_id),
            {
                "reverted": True,
                "reverted_at": now,
                "revert_event_id": revert_event_id,
                "updated_at": now,
            },
            merge=True,
        )

    async def clear_reverted(self, message_id: IntStr) -> None:
        now = self._now()
        await self._q_set(
            self._doc(message_id),
            {
                "reverted": False,
                "reverted_at": None,
                "revert_event_id": None,
                "updated_at": now,
            },
            merge=True,
        )

    # ─────────────────────────
    # helpers for point flow
    # ─────────────────────────

    async def should_award(self, message_id: IntStr) -> bool:
        """
        加点してよいかの簡易判定。
        - has_image=True
        - awarded=False
        """
        data = await self.get_log(message_id)
        if not data:
            return False

        if not bool(data.get("has_image")):
            return False

        if bool(data.get("awarded")):
            return False

        return True

    async def should_revert(self, message_id: IntStr) -> bool:
        """
        削除時に減点してよいかの簡易判定。
        - awarded=True
        - reverted=False
        """
        data = await self.get_log(message_id)
        if not data:
            return False

        if not bool(data.get("awarded")):
            return False

        if bool(data.get("reverted")):
            return False

        return True

    # ─────────────────────────
    # query helpers
    # ─────────────────────────

    async def list_logs_by_channel(
        self,
        channel_id: IntStr,
        *,
        limit: int = 200,
        has_image_only: bool = False,
    ) -> List[Dict[str, Any]]:
        q = self.db.collection(self.root).where("channel_id", "==", int(channel_id))

        if has_image_only:
            q = q.where("has_image", "==", True)

        q = q.order_by("created_at", direction=firestore.Query.DESCENDING)

        out: List[Dict[str, Any]] = []
        try:
            i = 0
            async for snap in q.stream():
                i += 1
                if i > int(limit):
                    break
                d = snap.to_dict() or {}
                out.append(d)
        except Exception as e:
            logger.error(f"[FS_Message_Log] list_logs_by_channel error: {e}", exc_info=True)

        return out

    async def list_logs_by_user(
        self,
        user_id: IntStr,
        *,
        limit: int = 200,
        has_image_only: bool = False,
    ) -> List[Dict[str, Any]]:
        q = self.db.collection(self.root).where("user_id", "==", int(user_id))

        if has_image_only:
            q = q.where("has_image", "==", True)

        q = q.order_by("created_at", direction=firestore.Query.DESCENDING)

        out: List[Dict[str, Any]] = []
        try:
            i = 0
            async for snap in q.stream():
                i += 1
                if i > int(limit):
                    break
                d = snap.to_dict() or {}
                out.append(d)
        except Exception as e:
            logger.error(f"[FS_Message_Log] list_logs_by_user error: {e}", exc_info=True)

        return out

    # ─────────────────────────
    # maintenance
    # ─────────────────────────

    async def delete_log(self, message_id: IntStr) -> None:
        await self._q_delete(self._doc(message_id))