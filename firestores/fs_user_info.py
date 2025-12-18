# firestores/fs_profile.py

import logging
from typing import Any, Dict, Optional

from google.cloud.firestore_v1 import AsyncClient

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue

logger = logging.getLogger(__name__)


class FS_Profile:
    def __init__(self, queue_manager=firestore_queue) -> None:
        """
        Firestore プロフィール用ラッパー。
        - Users/{author_id}/Profile/main
        - Messages/{message_id}
        を扱う。
        """
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")

        self.db: AsyncClient = client.firestore_db
        self.queue = queue_manager

    # ─────────────────────────
    # Profile 追加 / 更新
    # ─────────────────────────

    async def add_profile_data(self, author_id: str, author_name: str, message_id: str) -> bool:
        """
        Firestoreキューを用いてプロフィールデータを登録/更新する非同期メソッド。

        - Users/{author_id}/Profile/main
            - NAME
            - MESSAGE_ID
        - Messages/{message_id}
            - AUTHOR_ID
            - AUTHOR_NAME
        をバッチで書き込む。
        """
        async def runner():
            return await self._add_profile_data(author_id, author_name, message_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Profile] add_profile_data queue error: {e}", exc_info=True)
            return False

    async def _add_profile_data(self, author_id: str, author_name: str, message_id: str) -> bool:
        """
        実際の Firestore バックエンド実装。
        バッチ書き込みで Profile と Messages をまとめて更新する。
        """
        try:
            # Firestore リファレンス
            user_profile_ref = (
                self.db.collection("Users")
                .document(str(author_id))
                .collection("Profile")
                .document("main")
            )
            message_ref = self.db.collection("Messages").document(str(message_id))

            batch = self.db.batch()

            # Users/{author_id}/Profile/main
            doc_snapshot = await user_profile_ref.get()
            if not doc_snapshot.exists:
                batch.set(
                    user_profile_ref,
                    {
                        "NAME": author_name,
                        "MESSAGE_ID": message_id,
                    },
                )
                logger.info(f"[FS_Profile] New profile document created for user: {author_id}")
            else:
                batch.update(
                    user_profile_ref,
                    {
                        "NAME": author_name,
                        "MESSAGE_ID": message_id,
                    },
                )
                logger.info(f"[FS_Profile] Profile document updated for user: {author_id}")

            # Messages/{message_id} （merge 相当）
            batch.set(
                message_ref,
                {
                    "AUTHOR_ID": author_id,
                    "AUTHOR_NAME": author_name,
                },
                merge=True,
            )

            await batch.commit()
            logger.info(f"[FS_Profile] Message doc {message_id} updated with author {author_id}.")
            return True

        except Exception as e:
            logger.error(f"[FS_Profile] add_profile_data failed: {e}", exc_info=True)
            return False

    # ─────────────────────────
    # Profile 取得
    # ─────────────────────────

    async def get_profile_data(self, author_id: str) -> Optional[Dict[str, Any]]:
        """
        Firestoreキューを用いてプロフィールデータを取得するメソッド。
        - Users/{author_id}/Profile/main を取得して dict or None を返す。
        """
        async def runner():
            return await self._get_profile_data(author_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Profile] get_profile_data queue error: {e}", exc_info=True)
            return None

    async def _get_profile_data(self, author_id: str) -> Optional[Dict[str, Any]]:
        """
        実際に Firestore から読み込みを行う実装部分。
        - Users/{author_id}/Profile/main を GET してデータを返す。
        """
        try:
            user_ref = self.db.collection("Users").document(str(author_id))
            profile_ref = user_ref.collection("Profile").document("main")
            doc_snapshot = await profile_ref.get()

            if not doc_snapshot.exists:
                logger.info(f"[FS_Profile] No profile found for user: {author_id}")
                return None

            data = doc_snapshot.to_dict() or {}
            return data

        except Exception as e:
            logger.error(f"[FS_Profile] get_profile_data failed: {e}", exc_info=True)
            return None
