# firestores/fs_recruit.py みたいな想定

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from google.cloud.firestore_v1 import AsyncClient, ArrayUnion
from google.cloud.firestore_v1.async_transaction import async_transactional
from google.cloud.firestore_v1.base_query import FieldFilter

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue

logger = logging.getLogger(__name__)

IntStr = Union[int, str]


# ============================================================
# FS_Number : 募集用の通し番号（Recruitments/Number）
# ============================================================

class FS_Number:
    def __init__(self, queue_manager=firestore_queue) -> None:
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")

        self.db: AsyncClient = client.firestore_db
        self.queue = queue_manager

    async def get_number(self) -> Union[int, str]:
        """
        FireStore の通し番号をトランザクションで取得・更新。
        失敗時は "ERROR" を返す。
        """
        async def runner():
            return await self._get_number()

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Number] get_number queue error: {e}")
            return "ERROR"

    async def _get_number(self) -> Union[int, str]:
        """Firestore の通し番号を非同期トランザクションで取得・更新（競合防止）"""
        try:
            number_ref = self.db.collection("Recruitments").document("Number")

            @async_transactional
            async def transaction_operation(transaction, doc_ref):
                number_doc = await doc_ref.get()

                if not number_doc.exists:
                    now_count = 1
                    transaction.set(doc_ref, {"current_number": now_count}, merge=True)
                else:
                    doc_data = number_doc.to_dict() or {}
                    now_count = int(doc_data.get("current_number", 0)) + 1
                    transaction.update(doc_ref, {"current_number": now_count})

                logger.debug(f"[FS_Number] 取得した通し番号: {now_count}")
                return now_count

            current_number = await transaction_operation(self.db.transaction(), number_ref)
            return current_number

        except Exception as e:
            logger.error(f"[FS_Number] 通し番号の取得に失敗しました: {e}")
            return "ERROR"


# ============================================================
# FS_Recruitments : 募集データ本体 (Recruitments コレクション)
# ============================================================

class FS_Recruitments:
    def __init__(self, queue_manager=firestore_queue) -> None:
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")

        self.db: AsyncClient = client.firestore_db
        self.queue = queue_manager

    # ------------- add / set -------------

    async def add_recruit_data(self, owner_id: int, data: Dict[str, Any]) -> Union[str, None]:
        async def runner():
            return await self._add_recruit_data(owner_id, data)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Recruitments] add_recruit_data queue error: {e}")
            return "ERROR"

    async def _add_recruit_data(self, owner_id: int, data: Dict[str, Any]) -> Union[str, None]:
        """Firestore に募集データを登録"""
        try:
            user_ref = self.db.collection("Recruitments").document(str(owner_id))

            await user_ref.set(data, merge=True)

            logger.debug(
                f"[FS_Recruitments] 募集データを追加: Owner_ID={owner_id}, "
                f"Message_ID={data.get('Message_ID')}"
            )
            return data.get("Message_ID")

        except Exception as e:
            logger.error(f"[FS_Recruitments] 募集データの追加に失敗しました: {e}")
            return "ERROR"

    # ------------- query / get -------------

    async def get_recruit_data(self, user_id: int, anonymity: Optional[str] = None) -> Union[List[Dict[str, Any]], str]:
        async def runner():
            return await self._get_recruit_data(user_id, anonymity)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Recruitments] get_recruit_data queue error: {e}")
            return "ERROR"

    async def _get_recruit_data(self, user_id: int, anonymity: Optional[str]) -> Union[List[Dict[str, Any]], str]:
        """
        Firestore から `Allowed_Users` に `user_id` が含まれる募集を取得し、
        Anonymity でフィルタリング（"Signed" / "Anonymous"）した結果を UI 用辞書に整形。
        """
        try:
            query = self.db.collection("Recruitments")

            # Allowed_Users に user_id が含まれるクエリ
            query = query.where(
                filter=FieldFilter("Allowed_Users", "array_contains", str(user_id))
            )

            # Anonymity が指定されていればクエリに追加
            if anonymity in ("Signed", "Anonymous"):
                query = query.where(
                    filter=FieldFilter("Anonymity", "==", anonymity)
                )

            docs = query.stream()

            recruit_list: List[Dict[str, Any]] = []
            async for doc in docs:
                recruit_data = doc.to_dict() or {}
                recruit_list.append(
                    {
                        "Content": recruit_data.get("Content", "No Content"),
                        "DesireTime": recruit_data.get("Desire_Time", "Unknown Time"),
                        "PostedTime": recruit_data.get("Posted_Time", "Unknown Time"),
                        "MessageID": recruit_data.get("Message_ID", "0"),
                        "owner_id": doc.id,
                    }
                )

            # 投稿日時でソート (最新のものを上に)
            recruit_list.sort(key=lambda x: x["PostedTime"], reverse=True)

            logger.debug(f"[FS_Recruitments] 取得した募集データ: {recruit_list}")
            return recruit_list

        except Exception as e:
            logger.error(f"[FS_Recruitments] 募集データの取得に失敗しました: {e}")
            return "ERROR"

    async def get_content_data(self, user_id: int) -> Union[Dict[str, Any], None, str]:
        async def runner():
            return await self._get_content_data(user_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Recruitments] get_content_data queue error: {e}")
            return "ERROR"

    async def _get_content_data(self, user_id: int) -> Union[Dict[str, Any], None, str]:
        """Firestore から `user_id` のドキュメントを取得し、辞書データを返す"""
        try:
            user_ref = self.db.collection("Recruitments").document(str(user_id))
            user_doc = await user_ref.get()

            if not user_doc.exists:
                logger.debug(f"[FS_Recruitments] ユーザー {user_id} のデータが見つかりませんでした。")
                return None

            user_data = user_doc.to_dict() or {}
            logger.debug(f"[FS_Recruitments] 取得したデータ: {user_data}")
            return user_data

        except Exception as e:
            logger.error(f"[FS_Recruitments] Firestore からのデータ取得に失敗しました: {e}")
            return "ERROR"

    async def check_data(self, owner_id: int) -> str:
        async def runner():
            return await self._check_data(owner_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Recruitments] check_data queue error: {e}")
            return "ERROR"

    async def _check_data(self, owner_id: int) -> str:
        try:
            user_ref = self.db.collection("Recruitments").document(str(owner_id))
            user_doc = await user_ref.get()

            return "FOUND" if user_doc.exists else None
        except Exception as e:
            logger.error(f"[FS_Recruitments] データチェックに失敗しました (owner_id={owner_id}): {e}")
            return "ERROR"

    async def delete_data(self, owner_id: int) -> str:
        async def runner():
            return await self._delete_data(owner_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Recruitments] delete_data queue error: {e}")
            return "ERROR"

    async def _delete_data(self, owner_id: int) -> str:
        try:
            user_ref = self.db.collection("Recruitments").document(str(owner_id))
            await user_ref.delete()
            return "DELETE"
        except Exception as e:
            logger.error(f"[FS_Recruitments] データ削除に失敗しました (owner_id={owner_id}): {e}")
            return "ERROR"

    async def get_number_to_id(self, message_id: str) -> Union[str, None]:
        async def runner():
            return await self._get_number_to_id(message_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Recruitments] get_number_to_id queue error: {e}")
            return "ERROR"

    async def _get_number_to_id(self, message_id: str) -> Union[str, None]:
        """Firestore から `Message_ID` が一致するドキュメントの ID を取得"""
        try:
            docs = (
                self.db.collection("Recruitments")
                .where(filter=FieldFilter("Message_ID", "==", message_id))
                .stream()
            )

            doc_id: Optional[str] = None
            async for doc in docs:
                doc_id = doc.id

            return doc_id

        except Exception as e:
            logger.error(f"[FS_Recruitments] 募集データの取得に失敗しました: {e}")
            return "ERROR"

    async def loop_delete_data(self, current_time_str: str):
        async def runner():
            return await self._loop_delete_data(current_time_str)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Recruitments] loop_delete_data queue error: {e}")
            return []

    async def _loop_delete_data(self, current_time_str: str):
        """
        current_time_str: "YYYY-MM-DD HH:MM:SS" 形式の文字列
        - Posted_Time が 24時間以上前の募集を削除し、その Thread_ID を返す
        """
        try:
            current_time = datetime.strptime(current_time_str, "%Y-%m-%d %H:%M:%S")
            threshold_time = current_time - timedelta(hours=24)

            data_ref = self.db.collection("Recruitments")
            query = data_ref.stream()

            batch = self.db.batch()
            thread_ids: List[str] = []

            async for doc in query:
                doc_data = doc.to_dict() or {}
                doc_id = doc.id

                posted_str = doc_data.get("Posted_Time")
                if not posted_str:
                    continue

                try:
                    posted_time = datetime.strptime(posted_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    logger.warning(f"[FS_Recruitments] Posted_Time の形式が不正: {posted_str} (doc_id={doc_id})")
                    continue

                if posted_time < threshold_time:
                    logger.info(
                        f"[FS_Recruitments] 削除対象: ID={doc_id}, "
                        f"Posted_Time={posted_str}, Thread_ID={doc_data.get('Thread_ID', 'N/A')}"
                    )
                    batch.delete(doc.reference)

                    if "Thread_ID" in doc_data:
                        thread_ids.append(str(doc_data["Thread_ID"]))

            await batch.commit()
            logger.info(f"[FS_Recruitments] Firestore から {len(thread_ids)} 件のデータを削除しました。")
            return thread_ids

        except Exception as e:
            logger.error(f"[FS_Recruitments] Error deleting documents: {e}")
            return []


# ============================================================
# FS_Rec_Message : Recruit_Message (number 単位で entries 配列)
# ============================================================

class FS_Rec_Message:
    def __init__(self, queue_manager=firestore_queue) -> None:
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")

        self.db: AsyncClient = client.firestore_db
        self.queue = queue_manager

    async def add_data(self, number: int, user_id: int, thread_id: int, message_id: int) -> str:
        async def runner():
            return await self._add_data(number, user_id, thread_id, message_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Rec_Message] add_data queue error: {e}")
            return "ERROR"

    async def _add_data(self, number: int, user_id: int, thread_id: int, message_id: int) -> str:
        """
        同じ number のドキュメントに複数ユーザーの情報を entries 配列で管理する。
        既に同じ User_ID が含まれていれば FOUND を返す。
        """
        try:
            data_ref = self.db.collection("Recruit_Message").document(str(number))

            existing_doc = await data_ref.get()
            if existing_doc.exists:
                doc_data = existing_doc.to_dict() or {}
                entries: List[Dict[str, Any]] = doc_data.get("entries", [])

                if any(entry.get("User_ID") == str(user_id) for entry in entries):
                    return "FOUND"

                await data_ref.update(
                    {
                        "entries": ArrayUnion(
                            [
                                {
                                    "User_ID": str(user_id),
                                    "Thread_ID": str(thread_id),
                                    "Message_ID": str(message_id),
                                }
                            ]
                        )
                    }
                )

            else:
                await data_ref.set(
                    {
                        "entries": [
                            {
                                "User_ID": str(user_id),
                                "Thread_ID": str(thread_id),
                                "Message_ID": str(message_id),
                            }
                        ]
                    }
                )

            return "ADD"

        except Exception as e:
            logger.error(f"[FS_Rec_Message] データ追加に失敗しました (number={number}, user_id={user_id}): {e}")
            return "ERROR"

    async def get_data(self, number: int, user_id: int):
        async def runner():
            return await self._get_data(number, user_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Rec_Message] get_data queue error: {e}")
            return "ERROR"

    async def _get_data(self, number: int, user_id: int):
        """
        number ドキュメントから `entries` を取得し、該当する user_id のデータを返す。
        例: { "User_ID": "123", "Thread_ID": "456", "Message_ID": "789" }
        存在しない場合は None
        """
        try:
            data_ref = self.db.collection("Recruit_Message").document(str(number))
            doc_snapshot = await data_ref.get()

            if not doc_snapshot.exists:
                logger.debug(f"[FS_Rec_Message] ドキュメントが存在しません: number={number}")
                return None

            doc_data = doc_snapshot.to_dict() or {}
            entries: List[Dict[str, Any]] = doc_data.get("entries", [])

            for entry in entries:
                if entry.get("User_ID") == str(user_id):
                    return entry

            return None

        except Exception as e:
            logger.error(f"[FS_Rec_Message] get_dataに失敗 (number={number}, user_id={user_id}): {e}")
            return "ERROR"

    async def delete_data(self, number: int, user_id: int) -> str:
        async def runner():
            return await self._delete_data(number, user_id)

        try:
            return await self.queue.enqueue(runner)
        except Exception as e:
            logger.error(f"[FS_Rec_Message] delete_data queue error: {e}")
            return "ERROR"

    async def _delete_data(self, number: int, user_id: int) -> str:
        """
        number ドキュメントから `entries` 配列内の user_id に該当する要素を削除し、Firestore を更新する。
        """
        try:
            data_ref = self.db.collection("Recruit_Message").document(str(number))
            doc_snapshot = await data_ref.get()

            if not doc_snapshot.exists:
                logger.debug(f"[FS_Rec_Message] ドキュメントが存在しません: number={number}")
                return "NOT_FOUND"

            doc_data = doc_snapshot.to_dict() or {}
            entries: List[Dict[str, Any]] = doc_data.get("entries", [])

            new_entries = [entry for entry in entries if entry.get("User_ID") != str(user_id)]

            if len(entries) == len(new_entries):
                logger.debug(
                    f"[FS_Rec_Message] 削除対象が見つかりませんでした: (number={number}, user_id={user_id})"
                )
                return "NOT_FOUND"

            await data_ref.update({"entries": new_entries})
            return "DELETED"

        except Exception as e:
            logger.error(f"[FS_Rec_Message] delete_dataに失敗 (number={number}, user_id={user_id}): {e}")
            return "ERROR"
