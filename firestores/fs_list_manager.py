# firestores/fs_subscribe_lists.py

import logging
from typing import Any, Dict, List, Optional

from google.cloud.firestore_v1 import AsyncClient
from google.api_core.exceptions import NotFound, Forbidden

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500  # 1チャンクあたりの最大エントリ数


# ============================================================
# 共通: Firestore AsyncClient チェック用ヘルパー
# ============================================================

def _get_async_db() -> AsyncClient:
    if not isinstance(client.firestore_db, AsyncClient):
        raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")
    return client.firestore_db


# ============================================================
# FS_MyList
# ============================================================

class FS_MyList(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    # ---------- add_list ----------

    async def add_list(self, owner_id, owner_name, target_id, target_name):
        async def runner():
            return await self._add_list(owner_id, owner_name, target_id, target_name)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_MyList] add_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _add_list(self, owner_id, owner_name, target_id, target_name):
        # 受け取りは int/str 混在を許容し、内部では str に統一
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("MyList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            if not owner_meta_doc.exists:
                await owner_meta_ref.set({"total_count": 0, "chunk_count": 1})
                owner_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"MyListのmeta情報を初期化しました: {owner_id}")
            else:
                owner_meta_data = owner_meta_doc.to_dict() or {}

            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("MyList_from").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if not target_meta_doc.exists:
                await target_meta_ref.set({"total_count": 0, "chunk_count": 1})
                target_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"MyList_fromのmeta情報を初期化しました: {target_id}")
            else:
                target_meta_data = target_meta_doc.to_dict() or {}

            total_count = owner_meta_data.get("total_count", 0)
            max_limit = 80

            # 上限チェック
            if total_count >= max_limit:
                logger.warning(
                    f"ユーザー {owner_id} のMyListが上限に達しています "
                    f"(上限: {max_limit}, 現在: {total_count})"
                )
                return "LIMIT"

            # 現在のチャンクにデータを追加
            owner_chunk_ref = owner_ref.collection("MyList").document(
                f"chunk_{owner_meta_data['chunk_count']}"
            )
            target_chunk_ref = target_ref.collection("MyList_from").document(
                f"chunk_{target_meta_data['chunk_count']}"
            )

            owner_chunk_doc = await owner_chunk_ref.get()
            target_chunk_doc = await target_chunk_ref.get()

            owner_chunk_data = owner_chunk_doc.to_dict() if owner_chunk_doc.exists else {"entries": []}
            target_chunk_data = target_chunk_doc.to_dict() if target_chunk_doc.exists else {"entries": []}

            if len(owner_chunk_data["entries"]) >= CHUNK_SIZE:
                owner_meta_data["chunk_count"] += 1
                owner_chunk_ref = owner_ref.collection("MyList").document(
                    f"chunk_{owner_meta_data['chunk_count']}"
                )
                owner_chunk_data = {"entries": []}

            if len(target_chunk_data["entries"]) >= CHUNK_SIZE:
                target_meta_data["chunk_count"] += 1
                target_chunk_ref = target_ref.collection("MyList_from").document(
                    f"chunk_{target_meta_data['chunk_count']}"
                )
                target_chunk_data = {"entries": []}

            # --- 両者の存在チェック（整合性確認） ---
            owner_has_target = any(str(entry.get("id")) == target_id for entry in owner_chunk_data["entries"])
            target_has_owner = any(str(entry.get("id")) == owner_id for entry in target_chunk_data["entries"])

            if owner_has_target and target_has_owner:
                logger.info(f"双方のMyListに既に存在します: {owner_id} <-> {target_id}")
                return "FOUND"

            # 不整合の補完
            if not owner_has_target:
                owner_chunk_data["entries"].append({"id": target_id, "name": target_name})
                await owner_chunk_ref.set(owner_chunk_data)
                owner_meta_data["total_count"] = owner_meta_data.get("total_count", 0) + 1
                await owner_meta_ref.update(owner_meta_data)
                logger.warning(f"🔧 MyListの不整合修正: {owner_id} -> {target_id}")

            if not target_has_owner:
                target_chunk_data["entries"].append({"id": owner_id, "name": owner_name})
                await target_chunk_ref.set(target_chunk_data)
                target_meta_data["total_count"] = target_meta_data.get("total_count", 0) + 1
                await target_meta_ref.update(target_meta_data)
                logger.warning(f"🔧 MyList_fromの不整合修正: {target_id} -> {owner_id}")

            logger.info(f"MyListとMyList_fromに対象ユーザーを追加しました: {owner_id} -> {target_id}")
            return "ADD"

        except Exception as e:
            logger.error(f"MyListまたはMyList_fromへの追加に失敗しました: {e}", exc_info=True)
            return "ERROR"

    # ---------- get_list ----------

    async def get_list(self, owner_id):
        async def runner():
            return await self._get_list(owner_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_MyList] get_list queue error: {e}", exc_info=True)
            return "NOT_FOUND"

    async def _get_list(self, owner_id):
        owner_id = str(owner_id)

        try:
            user_ref = self.db.collection("Users").document(owner_id)
            meta_ref = user_ref.collection("MyList").document("meta")
            meta_doc = await meta_ref.get()

            if not meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のMyListが存在しません。")
                return "NOT_FOUND"

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)

            all_entries: List[Dict[str, Any]] = []
            for chunk_index in range(1, chunk_count + 1):
                chunk_ref = user_ref.collection("MyList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()
                if chunk_doc.exists:
                    chunk_data = chunk_doc.to_dict() or {}
                    all_entries.extend(chunk_data.get("entries", []))

            logger.info(f"MyListを取得しました: {owner_id} -> {len(all_entries)}件")
            return all_entries

        except Exception as e:
            logger.error(f"MyListの取得に失敗しました: {e}", exc_info=True)
            return "NOT_FOUND"

    # ---------- remove_list ----------

    async def remove_list(self, owner_id, target_id):
        async def runner():
            return await self._remove_list(owner_id, target_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_MyList] remove_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _remove_list(self, owner_id, target_id):
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("MyList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            # ① owner側メタがない → 既に削除済みとみなす
            if not owner_meta_doc.exists:
                logger.info(f"[MyList] owner meta missing -> already removed: owner={owner_id}, target={target_id}")
                return "REMOVED"

            owner_meta = owner_meta_doc.to_dict() or {}
            owner_chunk_count = int(owner_meta.get("chunk_count", 0))
            total_removed_owner = 0

            # ② owner側から target_id を削除
            for chunk_index in range(1, owner_chunk_count + 1):
                chunk_ref = owner_ref.collection("MyList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()
                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])

                before = len(entries)
                new_entries = [e for e in entries if str(e.get("id")) != target_id]
                removed = before - len(new_entries)

                if removed > 0:
                    await chunk_ref.set({"entries": new_entries})
                    total_removed_owner += removed
                    logger.info(
                        f"[MyList] removed {removed} entry from owner chunk: "
                        f"owner={owner_id}, target={target_id}, chunk={chunk_index}"
                    )
                    break

            # ③ owner側 total_count 更新
            if total_removed_owner > 0:
                new_total = max(0, int(owner_meta.get("total_count", 0)) - total_removed_owner)
                await owner_meta_ref.update({"total_count": new_total})
            else:
                logger.info(f"[MyList] not found in owner list (already removed): owner={owner_id}, target={target_id}")

            # ④ target側 (MyList_from)
            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("MyList_from").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if target_meta_doc.exists:
                target_meta = target_meta_doc.to_dict() or {}
                target_chunk_count = int(target_meta.get("chunk_count", 0))
                total_removed_target = 0

                for chunk_index in range(1, target_chunk_count + 1):
                    chunk_ref = target_ref.collection("MyList_from").document(f"chunk_{chunk_index}")
                    chunk_doc = await chunk_ref.get()
                    if not chunk_doc.exists:
                        continue

                    chunk_data = chunk_doc.to_dict() or {}
                    entries = chunk_data.get("entries", [])

                    before = len(entries)
                    new_entries = [e for e in entries if str(e.get("id")) != owner_id]
                    removed = before - len(new_entries)

                    if removed > 0:
                        await chunk_ref.set({"entries": new_entries})
                        total_removed_target += removed
                        logger.info(
                            f"[MyList_from] removed {removed} entry from target chunk: "
                            f"target={target_id}, owner={owner_id}, chunk={chunk_index}"
                        )
                        break

                if total_removed_target > 0:
                    new_total = max(0, int(target_meta.get("total_count", 0)) - total_removed_target)
                    await target_meta_ref.update({"total_count": new_total})
            else:
                logger.info(f"[MyList_from] target meta missing (ok): target={target_id}")

            return "REMOVED"

        except Exception as e:
            logger.exception(f"MyList remove failed: owner={owner_id}, target={target_id}: {e}")
            return "ERROR"

    # ---------- rebuild_list_from ----------

    async def rebuild_list_from(self, member_name_map: Dict[str, str]):
        async def runner():
            return await self._rebuild_list_from(member_name_map)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_MyList] rebuild_list_from queue error: {e}", exc_info=True)
            return "ERROR"

    async def _rebuild_list_from(self, member_name_map: Dict[str, str]):
        """
        Firestore の `MyList` を精査し、`MyList_from` を再構築する
        （重複登録なし + total_count 更新 + 正しい target_name の利用）
        """
        try:
            users_ref = self.db.collection("Users")
            mylist_map: Dict[str, List[Dict[str, Any]]] = {}

            # サーバーにいるユーザーのみ
            for user_id in member_name_map.keys():
                user_id_str = str(user_id)
                logger.info(f"ユーザー {user_id_str} の MyList を取得中")

                mylist_entries: List[Dict[str, Any]] = []
                mylist_ref = users_ref.document(user_id_str).collection("MyList")

                async for chunk in mylist_ref.stream():
                    chunk_data = chunk.to_dict() or {}
                    logger.info(f"ユーザー {user_id_str} の MyList チャンク: {chunk_data}")
                    mylist_entries.extend(chunk_data.get("entries", []))

                if mylist_entries:
                    mylist_map[user_id_str] = mylist_entries

            logger.info(f"MyList データ取得完了: {len(mylist_map)} ユーザー分のデータ")

            # MyList_from 再構築
            for owner_id, entries in mylist_map.items():
                owner_name = member_name_map.get(owner_id, "Unknown")
                for entry in entries:
                    target_id = entry.get("id")
                    if not target_id:
                        logger.warning(f"無効な target_id が検出されました: {entry}")
                        continue

                    target_id = str(target_id)
                    target_ref = users_ref.document(target_id)
                    target_mylist_from_ref = target_ref.collection("MyList_from")

                    # 既存entriesを全取得
                    target_entries: List[Dict[str, Any]] = []
                    async for chunk in target_mylist_from_ref.stream():
                        chunk_data = chunk.to_dict() or {}
                        target_entries.extend(chunk_data.get("entries", []))

                    existing_ids = {str(e.get("id")) for e in target_entries}
                    if owner_id in existing_ids:
                        logger.info(f"{owner_id} は既に {target_id} の MyList_from に登録済み")
                        continue

                    target_entries.append({"id": owner_id, "name": owner_name})
                    logger.info(f"{target_id} の MyList_from に {owner_id}（{owner_name}）を追加")

                    chunk_count = (len(target_entries) // CHUNK_SIZE) + 1
                    target_chunk_ref = target_mylist_from_ref.document(f"chunk_{chunk_count}")
                    await target_chunk_ref.set({"entries": target_entries})
                    logger.info(f"{target_id} の MyList_from を Firestore に保存しました")

                    target_meta_ref = target_ref.collection("MyList_from").document("meta")
                    target_meta_doc = await target_meta_ref.get()
                    target_meta_data = target_meta_doc.to_dict() if target_meta_doc.exists else {
                        "total_count": 0,
                        "chunk_count": 1,
                    }
                    target_meta_data["total_count"] = len(target_entries)
                    await target_meta_ref.set(target_meta_data, merge=True)

            logger.info("MyList_from の再構築が完了しました")
            return "SUCCESS"

        except Exception as e:
            logger.error(f"MyList_from の再構築に失敗しました: {e}", exc_info=True)
            return "ERROR"


# ============================================================
# FS_BlackList / FS_BlackList_From
# ============================================================

class FS_BlackList(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    async def add_list(self, owner_id, owner_name, target_id, target_name):
        async def runner():
            return await self._add_list(owner_id, owner_name, target_id, target_name)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_BlackList] add_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _add_list(self, owner_id, owner_name, target_id, target_name):
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("BlackList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            if not owner_meta_doc.exists:
                await owner_meta_ref.set({"total_count": 0, "chunk_count": 1})
                owner_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"BlackListのmeta情報を初期化しました: {owner_id}")
            else:
                owner_meta_data = owner_meta_doc.to_dict() or {}

            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("BlackList_from").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if not target_meta_doc.exists:
                await target_meta_ref.set({"total_count": 0, "chunk_count": 1})
                target_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"BlackList_fromのmeta情報を初期化しました: {target_id}")
            else:
                target_meta_data = target_meta_doc.to_dict() or {}

            total_count = owner_meta_data.get("total_count", 0)
            max_limit = 80

            if total_count >= max_limit:
                logger.warning(
                    f"ユーザー {owner_id} のBlackListが上限に達しています "
                    f"(上限: {max_limit}, 現在: {total_count})"
                )
                return "LIMIT"

            owner_chunk_ref = owner_ref.collection("BlackList").document(
                f"chunk_{owner_meta_data['chunk_count']}"
            )
            target_chunk_ref = target_ref.collection("BlackList_from").document(
                f"chunk_{target_meta_data['chunk_count']}"
            )

            owner_chunk_doc = await owner_chunk_ref.get()
            target_chunk_doc = await target_chunk_ref.get()

            owner_chunk_data = owner_chunk_doc.to_dict() if owner_chunk_doc.exists else {"entries": []}
            target_chunk_data = target_chunk_doc.to_dict() if target_chunk_doc.exists else {"entries": []}

            if len(owner_chunk_data["entries"]) >= CHUNK_SIZE:
                owner_meta_data["chunk_count"] += 1
                owner_chunk_ref = owner_ref.collection("BlackList").document(
                    f"chunk_{owner_meta_data['chunk_count']}"
                )
                owner_chunk_data = {"entries": []}

            if len(target_chunk_data["entries"]) >= CHUNK_SIZE:
                target_meta_data["chunk_count"] += 1
                target_chunk_ref = target_ref.collection("BlackList_from").document(
                    f"chunk_{target_meta_data['chunk_count']}"
                )
                target_chunk_data = {"entries": []}

            owner_has_target = any(str(entry.get("id")) == target_id for entry in owner_chunk_data["entries"])
            target_has_owner = any(str(entry.get("id")) == owner_id for entry in target_chunk_data["entries"])

            if owner_has_target and target_has_owner:
                logger.info(f"双方のBlackListに既に存在します: {owner_id} <-> {target_id}")
                return "FOUND"

            if not owner_has_target:
                owner_chunk_data["entries"].append({"id": target_id, "name": target_name})
                await owner_chunk_ref.set(owner_chunk_data)
                owner_meta_data["total_count"] = owner_meta_data.get("total_count", 0) + 1
                await owner_meta_ref.update(owner_meta_data)
                logger.warning(f"🔧 BlackListの不整合修正: {owner_id} -> {target_id}")

            if not target_has_owner:
                target_chunk_data["entries"].append({"id": owner_id, "name": owner_name})
                await target_chunk_ref.set(target_chunk_data)
                target_meta_data["total_count"] = target_meta_data.get("total_count", 0) + 1
                await target_meta_ref.update(target_meta_data)
                logger.warning(f"🔧 BlackList_fromの不整合修正: {target_id} -> {owner_id}")

            logger.info(f"BlackListとBlackList_fromに対象ユーザーを追加しました: {owner_id} -> {target_id}")
            return "ADD"

        except Exception as e:
            logger.error(f"BlackListまたはBlackList_fromへの追加に失敗しました: {e}", exc_info=True)
            return "ERROR"

    async def get_list(self, owner_id):
        async def runner():
            return await self._get_list(owner_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_BlackList] get_list queue error: {e}", exc_info=True)
            return "NOT_FOUND"

    async def _get_list(self, owner_id):
        owner_id = str(owner_id)

        try:
            user_ref = self.db.collection("Users").document(owner_id)
            meta_ref = user_ref.collection("BlackList").document("meta")
            meta_doc = await meta_ref.get()

            if not meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のBlackListが存在しません。")
                return "NOT_FOUND"

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)

            all_entries: List[Dict[str, Any]] = []
            for chunk_index in range(1, chunk_count + 1):
                chunk_ref = user_ref.collection("BlackList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()
                if chunk_doc.exists:
                    chunk_data = chunk_doc.to_dict() or {}
                    all_entries.extend(chunk_data.get("entries", []))

            logger.info(f"BlackListを取得しました: {owner_id} -> {len(all_entries)}件")
            return all_entries

        except Exception as e:
            logger.error(f"BlackListの取得に失敗しました: {e}", exc_info=True)
            return "NOT_FOUND"

    async def remove_list(self, owner_id, target_id):
        async def runner():
            return await self._remove_list(owner_id, target_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_BlackList] remove_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _remove_list(self, owner_id, target_id):
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("BlackList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            if not owner_meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のBlackListが存在しません。")
                return "NOT_FOUND"

            owner_meta_data = owner_meta_doc.to_dict() or {}
            removed = False

            for chunk_index in range(1, owner_meta_data.get("chunk_count", 0) + 1):
                chunk_ref = owner_ref.collection("BlackList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()

                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])
                new_entries = [e for e in entries if str(e.get("id")) != target_id]

                if len(new_entries) != len(entries):
                    await chunk_ref.set({"entries": new_entries})
                    owner_meta_data["total_count"] = max(
                        0, owner_meta_data.get("total_count", 0) - 1
                    )
                    await owner_meta_ref.update(owner_meta_data)
                    logger.info(f"BlackListから削除: {owner_id} -> {target_id}")
                    removed = True
                    break

            # target側
            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("BlackList_from").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if target_meta_doc.exists:
                target_meta_data = target_meta_doc.to_dict() or {}
                for chunk_index in range(1, target_meta_data.get("chunk_count", 0) + 1):
                    chunk_ref = target_ref.collection("BlackList_from").document(f"chunk_{chunk_index}")
                    chunk_doc = await chunk_ref.get()

                    if not chunk_doc.exists:
                        continue

                    chunk_data = chunk_doc.to_dict() or {}
                    entries = chunk_data.get("entries", [])
                    new_entries = [e for e in entries if str(e.get("id")) != owner_id]

                    if len(new_entries) != len(entries):
                        await chunk_ref.set({"entries": new_entries})
                        target_meta_data["total_count"] = max(
                            0, target_meta_data.get("total_count", 0) - 1
                        )
                        await target_meta_ref.update(target_meta_data)
                        logger.info(f"BlackList_fromから削除: {target_id} -> {owner_id}")
                        break

            return "REMOVED" if removed else "NOT_FOUND"

        except Exception as e:
            logger.error(f"BlackListまたはBlackList_fromからの削除に失敗しました: {e}", exc_info=True)
            return "ERROR"


class FS_BlackList_From(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    async def get_list(self, owner_id):
        async def runner():
            return await self._get_list(owner_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_BlackList_From] get_list queue error: {e}", exc_info=True)
            return "NOT_FOUND"

    async def _get_list(self, owner_id):
        owner_id = str(owner_id)

        try:
            user_ref = self.db.collection("Users").document(owner_id)
            meta_ref = user_ref.collection("BlackList_from").document("meta")
            meta_doc = await meta_ref.get()

            if not meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のBlackList_fromが存在しません。")
                return "NOT_FOUND"

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)

            all_entries: List[Dict[str, Any]] = []
            for chunk_index in range(1, chunk_count + 1):
                chunk_ref = user_ref.collection("BlackList_from").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()
                if chunk_doc.exists:
                    chunk_data = chunk_doc.to_dict() or {}
                    all_entries.extend(chunk_data.get("entries", []))

            logger.info(f"BlackList_fromを取得しました: {owner_id} -> {len(all_entries)}件")
            return all_entries

        except Exception as e:
            logger.error(f"BlackList_fromの取得に失敗しました: {e}", exc_info=True)
            return "NOT_FOUND"


# ============================================================
# FS_LikeList / FS_LikedList
# ============================================================

class FS_LikeList(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    async def add_list(self, owner_id, owner_name, target_id, target_name):
        async def runner():
            return await self._add_list(owner_id, owner_name, target_id, target_name)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_LikeList] add_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _add_list(self, owner_id, owner_name, target_id, target_name):
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("LikeList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            if not owner_meta_doc.exists:
                await owner_meta_ref.set({"total_count": 0, "chunk_count": 1})
                owner_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"LikeListのmeta情報を初期化しました: {owner_id}")
            else:
                owner_meta_data = owner_meta_doc.to_dict() or {}

            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("LikedList").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if not target_meta_doc.exists:
                await target_meta_ref.set({"total_count": 0, "chunk_count": 1})
                target_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"LikedListのmeta情報を初期化しました: {target_id}")
            else:
                target_meta_data = target_meta_doc.to_dict() or {}

            owner_chunk_ref = owner_ref.collection("LikeList").document(
                f"chunk_{owner_meta_data['chunk_count']}"
            )
            target_chunk_ref = target_ref.collection("LikedList").document(
                f"chunk_{target_meta_data['chunk_count']}"
            )

            owner_chunk_doc = await owner_chunk_ref.get()
            target_chunk_doc = await target_chunk_ref.get()

            owner_chunk_data = owner_chunk_doc.to_dict() if owner_chunk_doc.exists else {"entries": []}
            target_chunk_data = target_chunk_doc.to_dict() if target_chunk_doc.exists else {"entries": []}

            if len(owner_chunk_data["entries"]) >= CHUNK_SIZE:
                owner_meta_data["chunk_count"] += 1
                owner_chunk_ref = owner_ref.collection("LikeList").document(
                    f"chunk_{owner_meta_data['chunk_count']}"
                )
                owner_chunk_data = {"entries": []}

            if len(target_chunk_data["entries"]) >= CHUNK_SIZE:
                target_meta_data["chunk_count"] += 1
                target_chunk_ref = target_ref.collection("LikedList").document(
                    f"chunk_{target_meta_data['chunk_count']}"
                )
                target_chunk_data = {"entries": []}

            owner_has_target = any(str(entry.get("id")) == target_id for entry in owner_chunk_data["entries"])
            target_has_owner = any(str(entry.get("id")) == owner_id for entry in target_chunk_data["entries"])

            if owner_has_target and target_has_owner:
                logger.info(f"双方のLikeListに既に存在します: {owner_id} <-> {target_id}")
                return "FOUND"

            if not owner_has_target:
                owner_chunk_data["entries"].append({"id": target_id, "name": target_name})
                await owner_chunk_ref.set(owner_chunk_data)
                owner_meta_data["total_count"] = owner_meta_data.get("total_count", 0) + 1
                await owner_meta_ref.update(owner_meta_data)
                logger.warning(f"🔧 LikeListの不整合修正: {owner_id} -> {target_id}")

            if not target_has_owner:
                target_chunk_data["entries"].append({"id": owner_id, "name": owner_name})
                await target_chunk_ref.set(target_chunk_data)
                target_meta_data["total_count"] = target_meta_data.get("total_count", 0) + 1
                await target_meta_ref.update(target_meta_data)
                logger.warning(f"🔧 LikedListの不整合修正: {target_id} -> {owner_id}")

            logger.info(f"LikeListとLikedListに対象ユーザーを追加しました: {owner_id} -> {target_id}")
            return "ADD"

        except Exception as e:
            logger.error(f"LikeListまたはLikedListへの追加に失敗しました: {e}", exc_info=True)
            return "ERROR"

    async def get_list(self, owner_id):
        async def runner():
            return await self._get_list(owner_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_LikeList] get_list queue error: {e}", exc_info=True)
            return "NOT_FOUND"

    async def _get_list(self, owner_id):
        owner_id = str(owner_id)

        try:
            user_ref = self.db.collection("Users").document(owner_id)
            meta_ref = user_ref.collection("LikeList").document("meta")
            meta_doc = await meta_ref.get()

            if not meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のLikeListが存在しません。")
                return "NOT_FOUND"

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)

            all_entries: List[Dict[str, Any]] = []
            for chunk_index in range(1, chunk_count + 1):
                chunk_ref = user_ref.collection("LikeList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()
                if chunk_doc.exists:
                    chunk_data = chunk_doc.to_dict() or {}
                    all_entries.extend(chunk_data.get("entries", []))

            logger.info(f"LikeListを取得しました: {owner_id} -> {len(all_entries)}件")
            return all_entries

        except Exception as e:
            logger.error(f"LikeListの取得に失敗しました: {e}", exc_info=True)
            return "NOT_FOUND"

    async def remove_list(self, owner_id, target_id):
        async def runner():
            return await self._remove_list(owner_id, target_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_LikeList] remove_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _remove_list(self, owner_id, target_id):
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("LikeList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            if not owner_meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のLikeListが存在しません。")
                return "NOT_FOUND"

            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("LikedList").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if not target_meta_doc.exists:
                logger.info(f"ユーザー {target_id} のLikedListが存在しません。")
                return "NOT_FOUND"

            owner_meta_data = owner_meta_doc.to_dict() or {}
            target_meta_data = target_meta_doc.to_dict() or {}

            for chunk_index in range(1, owner_meta_data.get("chunk_count", 0) + 1):
                chunk_ref = owner_ref.collection("LikeList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()

                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])
                new_entries = [e for e in entries if str(e.get("id")) != target_id]

                if len(new_entries) != len(entries):
                    await chunk_ref.set({"entries": new_entries})
                    owner_meta_data["total_count"] = max(
                        0, owner_meta_data.get("total_count", 0) - 1
                    )
                    await owner_meta_ref.update(owner_meta_data)
                    logger.info(f"LikeListから対象ユーザーを削除しました: {owner_id} -> {target_id}")
                    break

            for chunk_index in range(1, target_meta_data.get("chunk_count", 0) + 1):
                chunk_ref = target_ref.collection("LikedList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()

                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])
                new_entries = [e for e in entries if str(e.get("id")) != owner_id]

                if len(new_entries) != len(entries):
                    await chunk_ref.set({"entries": new_entries})
                    target_meta_data["total_count"] = max(
                        0, target_meta_data.get("total_count", 0) - 1
                    )
                    await target_meta_ref.update(target_meta_data)
                    logger.info(f"LikedListから対象ユーザーを削除しました: {target_id} -> {owner_id}")
                    break

            return "REMOVED"

        except Exception as e:
            logger.error(f"LikeListまたはLikedListからの削除に失敗しました: {e}", exc_info=True)
            return "ERROR"


class FS_LikedList(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    async def get_list(self, owner_id):
        async def runner():
            return await self._get_list(owner_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_LikedList] get_list queue error: {e}", exc_info=True)
            return "NOT_FOUND"

    async def _get_list(self, owner_id):
        owner_id = str(owner_id)

        try:
            user_ref = self.db.collection("Users").document(owner_id)
            meta_ref = user_ref.collection("LikedList").document("meta")
            meta_doc = await meta_ref.get()

            if not meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のLikedListが存在しません。")
                return "NOT_FOUND"

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)

            all_entries: List[Dict[str, Any]] = []
            for chunk_index in range(1, chunk_count + 1):
                chunk_ref = user_ref.collection("LikedList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()
                if chunk_doc.exists:
                    chunk_data = chunk_doc.to_dict() or {}
                    all_entries.extend(chunk_data.get("entries", []))

            logger.info(f"LikedListを取得しました: {owner_id} -> {len(all_entries)}件")
            return all_entries

        except Exception as e:
            logger.error(f"LikedListの取得に失敗しました: {e}", exc_info=True)
            return "NOT_FOUND"

    async def get_counts_per_user(self):
        async def runner():
            return await self._get_counts_per_user()

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_LikedList] get_counts_per_user queue error: {e}", exc_info=True)
            return []

    async def _get_counts_per_user(self):
        try:
            users_ref = self.db.collection("Users")
            users_docs = await users_ref.list_documents()

            liked_counts: List[Dict[str, Any]] = []

            for user_doc in users_docs:
                user_id = user_doc.id
                meta_ref = user_doc.collection("LikedList").document("meta")
                meta_doc = await meta_ref.get()

                total_count = 0
                if meta_doc.exists:
                    meta_data = meta_doc.to_dict() or {}
                    total_count = meta_data.get("total_count", 0)

                liked_counts.append({"user_id": user_id, "total_count": total_count})

            logger.info(f"全ユーザーのLikedListの総数リストを取得しました: {len(liked_counts)} ユーザー")
            return liked_counts

        except Exception as e:
            logger.error(f"全ユーザーのLikedList数の取得に失敗しました: {e}", exc_info=True)
            return []


# ============================================================
# FS_DislikeList / FS_DislikedList
# ============================================================

class FS_DislikeList(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    async def add_list(self, owner_id, owner_name, target_id, target_name):
        async def runner():
            return await self._add_list(owner_id, owner_name, target_id, target_name)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_DislikeList] add_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _add_list(self, owner_id, owner_name, target_id, target_name):
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("DislikeList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            if not owner_meta_doc.exists:
                await owner_meta_ref.set({"total_count": 0, "chunk_count": 1})
                owner_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"DislikeListのmeta情報を初期化しました: {owner_id}")
            else:
                owner_meta_data = owner_meta_doc.to_dict() or {}

            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("DislikedList").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if not target_meta_doc.exists:
                await target_meta_ref.set({"total_count": 0, "chunk_count": 1})
                target_meta_data = {"total_count": 0, "chunk_count": 1}
                logger.info(f"DislikedListのmeta情報を初期化しました: {target_id}")
            else:
                target_meta_data = target_meta_doc.to_dict() or {}

            owner_chunk_ref = owner_ref.collection("DislikeList").document(
                f"chunk_{owner_meta_data['chunk_count']}"
            )
            target_chunk_ref = target_ref.collection("DislikedList").document(
                f"chunk_{target_meta_data['chunk_count']}"
            )

            owner_chunk_doc = await owner_chunk_ref.get()
            target_chunk_doc = await target_chunk_ref.get()

            owner_chunk_data = owner_chunk_doc.to_dict() if owner_chunk_doc.exists else {"entries": []}
            target_chunk_data = target_chunk_doc.to_dict() if target_chunk_doc.exists else {"entries": []}

            if len(owner_chunk_data["entries"]) >= CHUNK_SIZE:
                owner_meta_data["chunk_count"] += 1
                owner_chunk_ref = owner_ref.collection("DislikeList").document(
                    f"chunk_{owner_meta_data['chunk_count']}"
                )
                owner_chunk_data = {"entries": []}

            if len(target_chunk_data["entries"]) >= CHUNK_SIZE:
                target_meta_data["chunk_count"] += 1
                target_chunk_ref = target_ref.collection("DislikedList").document(
                    f"chunk_{target_meta_data['chunk_count']}"
                )
                target_chunk_data = {"entries": []}

            owner_has_target = any(str(entry.get("id")) == target_id for entry in owner_chunk_data["entries"])
            target_has_owner = any(str(entry.get("id")) == owner_id for entry in target_chunk_data["entries"])

            if owner_has_target and target_has_owner:
                logger.info(f"双方のDislikeListに既に存在します: {owner_id} <-> {target_id}")
                return "FOUND"

            if not owner_has_target:
                owner_chunk_data["entries"].append({"id": target_id, "name": target_name})
                await owner_chunk_ref.set(owner_chunk_data)
                owner_meta_data["total_count"] = owner_meta_data.get("total_count", 0) + 1
                await owner_meta_ref.update(owner_meta_data)
                logger.warning(f"🔧 DislikeListの不整合修正: {owner_id} -> {target_id}")

            if not target_has_owner:
                target_chunk_data["entries"].append({"id": owner_id, "name": owner_name})
                await target_chunk_ref.set(target_chunk_data)
                target_meta_data["total_count"] = target_meta_data.get("total_count", 0) + 1
                await target_meta_ref.update(target_meta_data)
                logger.warning(f"🔧 DislikedListの不整合修正: {target_id} -> {owner_id}")

            logger.info(f"DislikeListとDislikedListに対象ユーザーを追加しました: {owner_id} -> {target_id}")
            return "ADD"

        except Exception as e:
            logger.error(f"DislikeListまたはDislikedListへの追加に失敗しました: {e}", exc_info=True)
            return "ERROR"

    async def get_list(self, owner_id):
        async def runner():
            return await self._get_list(owner_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_DislikeList] get_list queue error: {e}", exc_info=True)
            return "NOT_FOUND"

    async def _get_list(self, owner_id):
        owner_id = str(owner_id)

        try:
            user_ref = self.db.collection("Users").document(owner_id)
            meta_ref = user_ref.collection("DislikeList").document("meta")
            meta_doc = await meta_ref.get()

            if not meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のDislikeListが存在しません。")
                return "NOT_FOUND"

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)

            all_entries: List[Dict[str, Any]] = []
            for chunk_index in range(1, chunk_count + 1):
                chunk_ref = user_ref.collection("DislikeList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()
                if chunk_doc.exists:
                    chunk_data = chunk_doc.to_dict() or {}
                    all_entries.extend(chunk_data.get("entries", []))

            logger.info(f"DislikeListを取得しました: {owner_id} -> {len(all_entries)}件")
            return all_entries

        except Exception as e:
            logger.error(f"DislikeListの取得に失敗しました: {e}", exc_info=True)
            return "NOT_FOUND"

    async def remove_list(self, owner_id, target_id):
        async def runner():
            return await self._remove_list(owner_id, target_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_DislikeList] remove_list queue error: {e}", exc_info=True)
            return "ERROR"

    async def _remove_list(self, owner_id, target_id):
        owner_id = str(owner_id)
        target_id = str(target_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            owner_meta_ref = owner_ref.collection("DislikeList").document("meta")
            owner_meta_doc = await owner_meta_ref.get()

            if not owner_meta_doc.exists:
                logger.info(f"ユーザー {owner_id} のDislikeListが存在しません。")
                return "NOT_FOUND"

            target_ref = self.db.collection("Users").document(target_id)
            target_meta_ref = target_ref.collection("DislikedList").document("meta")
            target_meta_doc = await target_meta_ref.get()

            if not target_meta_doc.exists:
                logger.info(f"ユーザー {target_id} のDislikedListが存在しません。")
                return "NOT_FOUND"

            owner_meta_data = owner_meta_doc.to_dict() or {}
            target_meta_data = target_meta_doc.to_dict() or {}

            for chunk_index in range(1, owner_meta_data.get("chunk_count", 0) + 1):
                chunk_ref = owner_ref.collection("DislikeList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()

                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])
                new_entries = [e for e in entries if str(e.get("id")) != target_id]

                if len(new_entries) != len(entries):
                    await chunk_ref.set({"entries": new_entries})
                    owner_meta_data["total_count"] = max(
                        0, owner_meta_data.get("total_count", 0) - 1
                    )
                    await owner_meta_ref.update(owner_meta_data)
                    logger.info(f"DislikeListから対象ユーザーを削除しました: {owner_id} -> {target_id}")
                    break

            for chunk_index in range(1, target_meta_data.get("chunk_count", 0) + 1):
                chunk_ref = target_ref.collection("DislikedList").document(f"chunk_{chunk_index}")
                chunk_doc = await chunk_ref.get()

                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])
                new_entries = [e for e in entries if str(e.get("id")) != owner_id]

                if len(new_entries) != len(entries):
                    await chunk_ref.set({"entries": new_entries})
                    target_meta_data["total_count"] = max(
                        0, target_meta_data.get("total_count", 0) - 1
                    )
                    await target_meta_ref.update(target_meta_data)
                    logger.info(f"DislikedListから対象ユーザーを削除しました: {target_id} -> {owner_id}")
                    break

            return "REMOVED"

        except Exception as e:
            logger.error(f"DislikeListまたはDislikedListからの削除に失敗しました: {e}", exc_info=True)
            return "ERROR"


class FS_DislikedList(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    async def get_counts_per_user(self):
        async def runner():
            return await self._get_counts_per_user()

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_DislikedList] get_counts_per_user queue error: {e}", exc_info=True)
            return []

    async def _get_counts_per_user(self):
        try:
            users_ref = self.db.collection("Users")
            users_docs = await users_ref.list_documents()

            disliked_counts: List[Dict[str, Any]] = []

            for user_doc in users_docs:
                user_id = user_doc.id
                meta_ref = user_doc.collection("DislikedList").document("meta")
                meta_doc = await meta_ref.get()

                total_count = 0
                if meta_doc.exists:
                    meta_data = meta_doc.to_dict() or {}
                    total_count = meta_data.get("total_count", 0)

                disliked_counts.append({"user_id": user_id, "total_count": total_count})

            logger.info(f"全ユーザーのDislikedListの総数リストを取得しました: {len(disliked_counts)} ユーザー")
            return disliked_counts

        except Exception as e:
            logger.error(f"全ユーザーのDislikedList数の取得に失敗しました: {e}", exc_info=True)
            return []


# ============================================================
# FS_DeleteList（脱退ユーザーのデータ削除）
# ============================================================

class FS_DeleteList(FirestoreBase):
    def __init__(self, queue_manager=firestore_queue) -> None:
        _get_async_db()  # validate AsyncClient
        super().__init__(queue_manager)

    async def remove_references_of_target(self, target_user_id: str) -> Dict[str, Any]:
        async def runner():
            return await self._remove_references_of_target_job(target_user_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_DeleteList] remove_references_of_target queue error: {e}", exc_info=True)
            return {"success": False, "errors": [{"step": "queue", "message": str(e)}]}

    async def _remove_references_of_target_job(self, target_user_id: str) -> Dict[str, Any]:
        target_user_id = str(target_user_id)

        summary: Dict[str, Any] = {
            "success": True,
            "errors": [],
        }

        steps = [
            ("LikeList", "LikedList"),
            ("LikedList", "LikeList"),
            ("DislikeList", "DislikedList"),
        ]

        try:
            target_ref = self.db.collection("Users").document(target_user_id)

            for from_subcol, to_subcol in steps:
                step_name = f"{from_subcol}->{to_subcol}"
                try:
                    ok = await self._remove_references_one_side(
                        from_user_ref=target_ref,
                        from_subcol_name=from_subcol,
                        to_subcol_name=to_subcol,
                        target_user_id=target_user_id,
                    )
                    if not ok:
                        summary["success"] = False
                        err_msg = f"Failed on step {step_name}"
                        logger.error(err_msg)
                        summary["errors"].append({"step": step_name, "message": err_msg})
                except Exception as e:
                    summary["success"] = False
                    err_msg = f"Exception on step {step_name}: {e}"
                    logger.error(err_msg, exc_info=True)
                    summary["errors"].append({"step": step_name, "message": str(e)})

            if summary["success"]:
                logger.info(f"All references to {target_user_id} have been removed from other users.")
            else:
                logger.error(f"Some steps failed while removing references of {target_user_id}")

        except Exception as e:
            summary["success"] = False
            err_msg = f"Exception in remove_references_of_target_job (outer): {e}"
            logger.error(err_msg, exc_info=True)
            summary["errors"].append({"step": "outer", "message": str(e)})

        return summary

    async def _remove_references_one_side(
        self,
        from_user_ref,
        from_subcol_name: str,
        to_subcol_name: str,
        target_user_id: str,
    ) -> bool:
        """
        - `from_user_ref` のサブコレクション from_subcol_name を見て、
          そこに含まれる「他ユーザー」の一覧を集める
        - その「他ユーザー」のドキュメントの to_subcol_name から target_user_id を削除
        """
        target_user_id = str(target_user_id)

        try:
            subcol_ref = from_user_ref.collection(from_subcol_name)
            meta_doc_ref = subcol_ref.document("meta")
            meta_doc = await meta_doc_ref.get()
            if not meta_doc.exists:
                logger.debug(f"No meta for {from_subcol_name} in {from_user_ref.id}")
                return True

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)

            user_ids_found: List[str] = []
            for i in range(1, chunk_count + 1):
                chunk_doc_ref = subcol_ref.document(f"chunk_{i}")
                chunk_doc = await chunk_doc_ref.get()
                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])
                for entry in entries:
                    other_user_id = entry.get("id")
                    if other_user_id:
                        user_ids_found.append(str(other_user_id))

            user_ids_found = list(set(user_ids_found))

            for other_user_id in user_ids_found:
                ok = await self._remove_id_from_subcol(
                    owner_id=other_user_id,
                    subcol_name=to_subcol_name,
                    remove_id=target_user_id,
                )
                if not ok:
                    return False

            return True

        except Exception as e:
            logger.error(
                f"Exception in _remove_references_one_side(from={from_subcol_name}, "
                f"to={to_subcol_name}, target={target_user_id}): {e}",
                exc_info=True,
            )
            return False

    async def _remove_id_from_subcol(self, owner_id: str, subcol_name: str, remove_id: str) -> bool:
        """
        owner_id の subcol_name から id == remove_id のエントリを削除し、
        meta.total_count を更新する。
        """
        owner_id = str(owner_id)
        remove_id = str(remove_id)

        try:
            owner_ref = self.db.collection("Users").document(owner_id)
            subcol_ref = owner_ref.collection(subcol_name)

            meta_doc_ref = subcol_ref.document("meta")
            meta_doc = await meta_doc_ref.get()
            if not meta_doc.exists:
                return True

            meta_data = meta_doc.to_dict() or {}
            chunk_count = meta_data.get("chunk_count", 0)
            total_count = meta_data.get("total_count", 0)
            total_removed = 0

            for i in range(1, chunk_count + 1):
                chunk_doc_ref = subcol_ref.document(f"chunk_{i}")
                chunk_doc = await chunk_doc_ref.get()
                if not chunk_doc.exists:
                    continue

                chunk_data = chunk_doc.to_dict() or {}
                entries = chunk_data.get("entries", [])

                new_entries = [e for e in entries if str(e.get("id")) != remove_id]
                removed_count = len(entries) - len(new_entries)
                if removed_count > 0:
                    chunk_data["entries"] = new_entries
                    await chunk_doc_ref.set(chunk_data)
                    total_removed += removed_count

            if total_removed > 0:
                meta_data["total_count"] = max(0, total_count - total_removed)
                await meta_doc_ref.update(meta_data)

            return True

        except Exception as e:
            logger.error(
                f"Exception in _remove_id_from_subcol(owner={owner_id}, "
                f"subcol={subcol_name}, remove_id={remove_id}): {e}",
                exc_info=True,
            )
            return False

    async def remove_target_user_doc(self, target_user_id: str) -> Dict[str, Any]:
        async def runner():
            return await self._remove_target_user_doc(target_user_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_DeleteList] remove_target_user_doc queue error: {e}", exc_info=True)
            return {"success": False, "errors": [{"step": "queue", "message": str(e)}]}

    async def _remove_target_user_doc(self, target_user_id: str) -> Dict[str, Any]:
        target_user_id = str(target_user_id)

        summary: Dict[str, Any] = {
            "success": True,
            "errors": [],
        }

        try:
            logger.info(f"Attempting to delete user document and its subcollections: {target_user_id}")
            user_ref = self.db.collection("Users").document(target_user_id)

            doc = await user_ref.get()
            subcollections = [c async for c in user_ref.collections()]
            has_subcollections = len(subcollections) > 0

            if (not doc.exists) and (not has_subcollections):
                logger.warning(f"User document {target_user_id} does not exist (no subcollections).")
                summary["success"] = False
                summary["errors"].append(
                    {"step": "check_exists", "message": "ドキュメントが存在しません。"}
                )
                return summary

            await self._recursive_delete(user_ref)
            logger.info(f"Deleted user document (and its subcollections if any): {target_user_id}")

        except Exception as e:
            summary["success"] = False
            logger.error(f"Failed to delete user document {target_user_id}: {e}", exc_info=True)
            summary["errors"].append({"step": "delete_user_doc", "message": str(e)})

        return summary

    async def _recursive_delete(self, doc_ref):
        """
        ドキュメントとそのすべてのサブコレクションを再帰的に削除
        """
        try:
            subcollections = [sc async for sc in doc_ref.collections()]
            for subcol in subcollections:
                async for subdoc in subcol.stream():
                    await self._recursive_delete(subdoc.reference)

            await doc_ref.delete()
            logger.debug(f"Deleted document: {doc_ref.path}")

        except NotFound:
            logger.warning(f"Document {doc_ref.path} not found.")
        except Forbidden:
            logger.error(f"Insufficient permissions to delete document {doc_ref.path}.")
            raise
        except Exception as e:
            logger.error(f"Error deleting document {doc_ref.path}: {e}", exc_info=True)
            raise
