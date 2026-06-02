import logging
from typing import Any, Dict, Optional

from google.cloud.firestore_v1 import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase

logger = logging.getLogger(__name__)


class FS_VC_TC_SYNC(FirestoreBase):
    """
    VC と TC の対応を Firestore に保存するラッパー。

    コレクション構造:
    (default)
    ┗ VC_TC_SYNC (collection)
      ┗ {VC_ID} (document)
        ┗ TC_ID (string field)

    - add_ids(vc_id, tc_id)
        VC_ID をキーに TC_ID を保存/更新
    - get_ids(vc_id=..., tc_id=...)
        VC_ID または TC_ID から対応ペアを取得
    - delete_ids(vc_id=..., tc_id=...)
        VC_ID または TC_ID から対応ペアを削除

    補助メソッド:
    - get_from_vc_id(vc_id) -> Optional[int]
    - get_from_tc_id(tc_id) -> Optional[int]
    - delete_from_vc_id(vc_id)
    - delete_from_tc_id(tc_id)
    """

    COLLECTION_NAME = "VC_TC_SYNC"

    def __init__(self, queue_manager=firestore_queue) -> None:
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")

        super().__init__(queue_manager)

    # ─────────────────────────
    # 追加 / 更新
    # ─────────────────────────

    async def add_ids(self, vc_id: int, tc_id: int) -> bool:
        """
        VC_ID と TC_ID のペアを保存/更新する。
        - ドキュメントID: VC_ID
        - フィールド: TC_ID (string)

        :param vc_id: VoiceChannel ID (int)
        :param tc_id: TextChannel ID (int)
        """
        async def runner():
            return await self._add_ids(vc_id, tc_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_VC_TC_SYNC] add_ids queue error: {e}", exc_info=True)
            return False

    async def _add_ids(self, vc_id: int, tc_id: int) -> bool:
        try:
            vc_doc_ref = self.db.collection(self.COLLECTION_NAME).document(str(vc_id))
            await vc_doc_ref.set({"TC_ID": str(tc_id)}, merge=True)

            logger.info(f"[FS_VC_TC_SYNC] Set mapping VC({vc_id}) -> TC({tc_id})")
            return True
        except Exception as e:
            logger.error(f"[FS_VC_TC_SYNC] _add_ids failed: {e}", exc_info=True)
            return False

    # ─────────────────────────
    # 取得
    # ─────────────────────────

    async def get_ids(
        self,
        *,
        vc_id: Optional[int] = None,
        tc_id: Optional[int] = None,
    ) -> Optional[Dict[str, int]]:
        """
        VC_ID または TC_ID を指定して対応ペアを取得する。

        - vc_id 指定時:
            VC_TC_SYNC/{vc_id} ドキュメントを取得
        - tc_id 指定時:
            VC_TC_SYNC コレクションから TC_ID == tc_id のドキュメントを検索

        戻り値例:
            {"VC_ID": 1234567890, "TC_ID": 9876543210}
        見つからなければ None
        """
        # VC_ID と TC_ID の両方 / 両方なしは受け付けない
        if (vc_id is None and tc_id is None) or (vc_id is not None and tc_id is not None):
            logger.error("[FS_VC_TC_SYNC] get_ids requires exactly one of vc_id or tc_id.")
            return None

        async def runner():
            return await self._get_ids(vc_id=vc_id, tc_id=tc_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_VC_TC_SYNC] get_ids queue error: {e}", exc_info=True)
            return None

    async def _get_ids(
        self,
        *,
        vc_id: Optional[int] = None,
        tc_id: Optional[int] = None,
    ) -> Optional[Dict[str, int]]:
        try:
            collection = self.db.collection(self.COLLECTION_NAME)

            # VC_ID から取得
            if vc_id is not None:
                doc_ref = collection.document(str(vc_id))
                snap = await doc_ref.get()

                if not snap.exists:
                    logger.info(f"[FS_VC_TC_SYNC] No mapping found for VC_ID={vc_id}")
                    return None

                data = snap.to_dict() or {}
                tc_value = data.get("TC_ID")
                if tc_value is None:
                    logger.warning(f"[FS_VC_TC_SYNC] Document for VC_ID={vc_id} has no TC_ID field.")
                    return None

                return {
                    "VC_ID": int(vc_id),
                    "TC_ID": int(tc_value),
                }

            # TC_ID から取得
            assert tc_id is not None  # 上で validation 済み
            tc_str = str(tc_id)

            query = collection.where(filter=FieldFilter("TC_ID", "==", tc_str)).limit(1)
            async for snap in query.stream():
                # ドキュメントIDが VC_ID
                vc_value = int(snap.id)
                return {
                    "VC_ID": vc_value,
                    "TC_ID": int(tc_str),
                }

            logger.info(f"[FS_VC_TC_SYNC] No mapping found for TC_ID={tc_id}")
            return None

        except Exception as e:
            logger.error(f"[FS_VC_TC_SYNC] _get_ids failed: {e}", exc_info=True)
            return None

    # ─────────────────────────
    # 削除
    # ─────────────────────────

    async def delete_ids(
        self,
        *,
        vc_id: Optional[int] = None,
        tc_id: Optional[int] = None,
    ) -> bool:
        """
        VC_ID または TC_ID を指定して対応ペアを削除する。

        - vc_id 指定時:
            その VC_ID のドキュメントを削除
        - tc_id 指定時:
            TC_ID == tc_id のドキュメントをすべて削除

        正常終了で True / 例外発生で False
        """
        if (vc_id is None and tc_id is None) or (vc_id is not None and tc_id is not None):
            logger.error("[FS_VC_TC_SYNC] delete_ids requires exactly one of vc_id or tc_id.")
            return False

        async def runner():
            return await self._delete_ids(vc_id=vc_id, tc_id=tc_id)

        try:
            return await self._run(runner)
        except Exception as e:
            logger.error(f"[FS_VC_TC_SYNC] delete_ids queue error: {e}", exc_info=True)
            return False

    async def _delete_ids(
        self,
        *,
        vc_id: Optional[int] = None,
        tc_id: Optional[int] = None,
    ) -> bool:
        try:
            collection = self.db.collection(self.COLLECTION_NAME)

            # VC_ID 指定で削除
            if vc_id is not None:
                doc_ref = collection.document(str(vc_id))
                snap = await doc_ref.get()
                if not snap.exists:
                    logger.info(f"[FS_VC_TC_SYNC] No mapping to delete for VC_ID={vc_id}")
                    return True  # 無いなら無いでOK（冪等）
                await doc_ref.delete()
                logger.info(f"[FS_VC_TC_SYNC] Deleted mapping for VC_ID={vc_id}")
                return True

            # TC_ID 指定で削除（該当するものを全部削除）
            assert tc_id is not None
            tc_str = str(tc_id)

            query = collection.where(filter=FieldFilter("TC_ID", "==", tc_str))
            deleted_count = 0

            async for snap in query.stream():
                await collection.document(snap.id).delete()
                deleted_count += 1

            if deleted_count == 0:
                logger.info(f"[FS_VC_TC_SYNC] No mapping to delete for TC_ID={tc_id}")
            else:
                logger.info(f"[FS_VC_TC_SYNC] Deleted {deleted_count} mapping(s) for TC_ID={tc_id}")

            return True

        except Exception as e:
            logger.error(f"[FS_VC_TC_SYNC] _delete_ids failed: {e}", exc_info=True)
            return False

    # ─────────────────────────
    # 補助メソッド
    # ─────────────────────────

    async def get_from_vc_id(self, vc_id: int) -> Optional[int]:
        """
        VC_ID から TC_ID だけを取得したい場合のショートカット。
        """
        data = await self.get_ids(vc_id=vc_id)
        return data["TC_ID"] if data is not None else None

    async def get_from_tc_id(self, tc_id: int) -> Optional[int]:
        """
        TC_ID から VC_ID だけを取得したい場合のショートカット。
        """
        data = await self.get_ids(tc_id=tc_id)
        return data["VC_ID"] if data is not None else None

    async def delete_from_vc_id(self, vc_id: int) -> bool:
        """
        VC_ID を指定して対応ペアを削除するショートカット。
        """
        return await self.delete_ids(vc_id=vc_id)

    async def delete_from_tc_id(self, tc_id: int) -> bool:
        """
        TC_ID を指定して対応ペアを削除するショートカット。
        """
        return await self.delete_ids(tc_id=tc_id)
