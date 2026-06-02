import logging
from typing import Dict, Optional, Tuple, Union
from datetime import datetime
from zoneinfo import ZoneInfo

from google.cloud.firestore_v1 import AsyncClient
from google.cloud import firestore_v1 as firestore  # noqa: F401  # 将来の拡張用に残しておく

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase

from discord import User

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateLike = Union[str, datetime]

class FS_Judging(FirestoreBase):
    ROOT_COLLECTION = "Judging"
    CATEGORY_KEYS = ("favorite", "circle", "cross", "caution")

    def __init__(
        self,
        root_collection: str = "Judging",
        queue_manager=firestore_queue,  # 型: QueueManager_FireStore インスタンス想定
    ):
        # Firestoreクライアント
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")
        super().__init__(queue_manager)
        self.root = root_collection

    # ------------- Helpers -------------

    @staticmethod
    def _find_user_index(category_map: Dict, user_id: str) -> Optional[str]:
        for idx, entry in category_map.items():
            if isinstance(entry, dict) and entry.get("user_id") == user_id:
                return idx
        return None

    @staticmethod
    def _next_index(category_map: Dict) -> str:
        return str(len(category_map))

    def _day_doc(self, target_id: str, message_id: str, date_ymd: str):
        return (
            self.db.collection(self.root)
            .document(target_id)
            .collection(message_id)
            .document(date_ymd)
        )

    async def _load_maps(
        self, target_id: str, message_id: str, date_ymd: str
    ) -> Tuple[Dict, Dict, Dict, Dict, bool]:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        snap = await doc_ref.get()
        if not snap or not snap.exists:
            logger.warning(f"Document not found: {target_id} - {message_id} - {date_ymd}")
            return {}, {}, {}, {}, False
        data = snap.to_dict() or {}
        return (
            dict(data.get("favorite", {}) or {}),
            dict(data.get("circle", {}) or {}),
            dict(data.get("cross", {}) or {}),
            dict(data.get("caution", {}) or {}),
            True,
        )

    # ------------- Read -------------

    async def exists(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> bool:
        async def runner():
            return await self._exists(str(target_id), str(message_id), str(date_ymd))
        try:
            return await self._run(runner) or False
        except Exception as e:
            logger.error(f"[FS_Judging] exists queue error: {e}", exc_info=True)
            return False

    async def _exists(self, target_id: str, message_id: str, date_ymd: str) -> bool:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        snap = await doc_ref.get()
        return snap.exists if snap else False

    async def get_entry(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> Dict[str, Dict]:
        async def runner():
            return await self._get_entry(str(target_id), str(message_id), str(date_ymd))
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging] get_entry queue error: {e}", exc_info=True)
            return {}

    async def _get_entry(self, target_id: str, message_id: str, date_ymd: str) -> Dict[str, Dict]:
        favorite, circle, cross, caution, _ = await self._load_maps(target_id, message_id, date_ymd)
        return {
            "favorite": favorite,
            "circle": circle,
            "cross": cross,
            "caution": caution,
        }

    async def get_category(
        self,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        category: str,
    ) -> Dict:
        async def runner():
            return await self._get_category(str(target_id), str(message_id), str(date_ymd), category)
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging] get_category queue error: {e}", exc_info=True)
            return {}

    async def _get_category(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        category: str,
    ) -> Dict:
        category = category.lower()
        if category not in self.CATEGORY_KEYS:
            raise ValueError("category must be one of favorite, circle, cross, caution")

        favorite, circle, cross, caution, _ = await self._load_maps(target_id, message_id, date_ymd)
        if category == "favorite":
            return favorite
        if category == "circle":
            return circle
        if category == "cross":
            return cross
        return caution  # caution

    # ------------- Write (favorite/circle/cross toggle + move exclusivity) -------------

    async def set_vote(
        self,
        category: str,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        user: Optional[User],
        comment: Optional[str] = None,
    ) -> str:
        async def runner():
            return await self._set_vote(category, str(target_id), str(message_id), str(date_ymd), user, comment)
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging] set_vote queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _set_vote(
        self,
        category: str,
        target_id: str,
        message_id: str,
        date_ymd: str,
        user: Optional[User],
        comment: Optional[str] = None,
    ) -> str:
        if user is None:
            raise ValueError("user must not be None")

        category = category.lower()

        # display_name が無いタイプ（純 User）の場合も考慮
        user_name = getattr(user, "display_name", None) or getattr(user, "name", str(user.id))
        user_id = str(user.id)

        if category in ("favorite", "circle", "cross"):
            return await self._set_simple_category(
                target_id=target_id,
                message_id=message_id,
                date_ymd=date_ymd,
                category=category,
                user_id=user_id,
                user_name=user_name,
            )

        elif category == "caution":
            return await self._set_caution(
                target_id=target_id,
                message_id=message_id,
                date_ymd=date_ymd,
                user_id=user_id,
                user_name=user_name,
                comment=comment,
            )

        raise ValueError("category must be one of favorite, circle, cross, caution")

    async def _set_simple_category(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        category: str,
        user_id: str,
        user_name: str,
    ) -> str:
        try:
            category = category.lower()
            doc_ref = self._day_doc(target_id, message_id, date_ymd)

            favorite, circle, cross, caution, _ = await self._load_maps(target_id, message_id, date_ymd)

            # 現在どのカテゴリにいるか
            favorite_idx = self._find_user_index(favorite, user_id)
            circle_idx = self._find_user_index(circle, user_id)
            cross_idx = self._find_user_index(cross, user_id)
            caution_idx = self._find_user_index(caution, user_id)

            # 同じカテゴリを押した → 取り消し
            if category == "favorite":
                current_idx = favorite_idx
                current_map = favorite
            elif category == "circle":
                current_idx = circle_idx
                current_map = circle
            else:  # "cross"
                current_idx = cross_idx
                current_map = cross

            if current_idx is not None:
                current_map.pop(current_idx, None)
                await doc_ref.set(
                    {
                        "favorite": favorite,
                        "circle": circle,
                        "cross": cross,
                        "caution": caution,
                    },
                    merge=True,
                )
                return "remove"

            # それ以外 → 排他（他カテゴリから削除）
            removed_from_other = any(
                idx is not None
                for idx in [favorite_idx, circle_idx, cross_idx, caution_idx]
            )

            if favorite_idx is not None:
                favorite.pop(favorite_idx)
            if circle_idx is not None:
                circle.pop(circle_idx)
            if cross_idx is not None:
                cross.pop(cross_idx)
            if caution_idx is not None:
                caution.pop(caution_idx)

            # 新規追加
            payload = {"user_id": user_id, "user_name": user_name}
            if category == "favorite":
                new_idx = self._next_index(favorite)
                favorite[new_idx] = payload
            elif category == "circle":
                new_idx = self._next_index(circle)
                circle[new_idx] = payload
            else:
                new_idx = self._next_index(cross)
                cross[new_idx] = payload

            await doc_ref.set(
                {
                    "favorite": favorite,
                    "circle": circle,
                    "cross": cross,
                    "caution": caution,
                },
                merge=True,
            )

            return "change" if removed_from_other else "add"
        except Exception as e:
            logger.error(f"Error in _set_simple_category: {e}")
            return "error_occurred"

    # ------------- Write (caution: empty-comment=cancel, else upsert/move) -------------

    async def set_caution(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        user_id: str,
        user_name: str,
        comment: Optional[str],
    ) -> str:
        async def runner():
            return await self._set_caution(target_id, message_id, date_ymd, user_id, user_name, comment)
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging] set_caution queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _set_caution(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        user_id: str,
        user_name: str,
        comment: Optional[str],
    ) -> str:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        favorite, circle, cross, caution, _ = await self._load_maps(target_id, message_id, date_ymd)

        norm = (comment or "").strip()

        # 各カテゴリでの index
        favorite_idx = self._find_user_index(favorite, user_id)
        circle_idx = self._find_user_index(circle, user_id)
        cross_idx = self._find_user_index(cross, user_id)
        caution_idx = self._find_user_index(caution, user_id)

        # コメント空白 → CAUTION のみ削除
        if norm == "":
            if caution_idx is not None:
                caution.pop(caution_idx, None)
                await doc_ref.set({"caution": caution}, merge=True)
                return "remove"
            return "no_change"

        # CAUTIONにすでにいる
        if caution_idx is not None:
            old_comment = (caution[caution_idx].get("comment") or "").strip()
            if old_comment == norm:
                return "no_change"

            # コメント上書き
            caution[caution_idx] = {
                "user_id": user_id,
                "user_name": user_name,
                "comment": norm,
            }
            await doc_ref.set({"caution": caution}, merge=True)
            return "change"

        # 他カテゴリ → CAUTIONに移動（排他）
        removed_from_other = any(
            idx is not None for idx in [circle_idx, favorite_idx, cross_idx]
        )

        if favorite_idx is not None:
            favorite.pop(favorite_idx)
        if circle_idx is not None:
            circle.pop(circle_idx)
        if cross_idx is not None:
            cross.pop(cross_idx)

        new_idx = self._next_index(caution)
        caution[new_idx] = {
            "user_id": user_id,
            "user_name": user_name,
            "comment": norm,
        }

        await doc_ref.set(
            {
                "favorite": favorite,
                "circle": circle,
                "cross": cross,
                "caution": caution,
            },
            merge=True,
        )

        return "change" if removed_from_other else "add"

    # ------------- Removal / Clear -------------

    async def remove_from_category(
        self,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        category: str,
        user_id: IntStr,
    ) -> str:
        async def runner():
            return await self._remove_from_category(
                str(target_id), str(message_id), str(date_ymd), category, str(user_id)
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging] remove_from_category queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _remove_from_category(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        category: str,
        user_id: str,
    ) -> None:
        category = category.lower()
        if category not in self.CATEGORY_KEYS:
            raise ValueError("category must be one of favorite, circle, cross, caution")

        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        favorite, circle, cross, caution, _ = await self._load_maps(target_id, message_id, date_ymd)

        if category == "favorite":
            idx = self._find_user_index(favorite, user_id)
            if idx is not None:
                favorite.pop(idx, None)
                await doc_ref.set({"favorite": favorite}, merge=True)
            return

        if category == "circle":
            idx = self._find_user_index(circle, user_id)
            if idx is not None:
                circle.pop(idx, None)
                await doc_ref.set({"circle": circle}, merge=True)
            return

        if category == "cross":
            idx = self._find_user_index(cross, user_id)
            if idx is not None:
                cross.pop(idx, None)
                await doc_ref.set({"cross": cross}, merge=True)
            return

        # caution
        idx = self._find_user_index(caution, user_id)
        if idx is not None:
            caution.pop(idx, None)
            await doc_ref.set({"caution": caution}, merge=True)

    async def clear_all_categories(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> str:
        async def runner():
            return await self._clear_all_categories(str(target_id), str(message_id), str(date_ymd))
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging] clear_all_categories queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _clear_all_categories(self, target_id: str, message_id: str, date_ymd: str) -> None:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        await doc_ref.set(
            {
                "favorite": {},
                "circle": {},
                "cross": {},
                "caution": {},
            },
            merge=True,
        )

    async def clear_message_date(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> str:
        async def runner():
            return await self._clear_message_date(str(target_id), str(message_id), str(date_ymd))
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging] clear_message_date queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _clear_message_date(self, target_id: str, message_id: str, date_ymd: str) -> None:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        await doc_ref.delete()

    async def init_day_entry(
        self,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        thread_id: IntStr,
        overwrite: bool = False,
    ) -> str:
        """
        ★新メソッド★
        指定された target_id / message_id / date_ymd のドキュメントを
        初期化して作成する。

        保存される内容：
            - thread_id (必須)
            - favorite / circle / cross / caution は空の map

        overwrite=True の場合、既存ドキュメントを完全上書きする。
        overwrite=False の場合、既に存在していたら何もせず "exists" を返す。
        """
        async def runner():
            return await self._init_day_entry(
                str(target_id), str(message_id), str(date_ymd), str(thread_id), overwrite
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging] init_day_entry queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _init_day_entry(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        thread_id: str,
        overwrite: bool = False,
    ) -> str:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)

        snap = await doc_ref.get()
        if snap and snap.exists and not overwrite:
            return "exists"

        data = {
            "thread_id": thread_id,
            "favorite": {},
            "circle": {},
            "cross": {},
            "caution": {},
        }

        # overwrite の場合 merge=False にして完全上書き
        await doc_ref.set(data, merge=not overwrite)

        return "initialized"

    async def get_all_for_target_date(
        self,
        target_id: IntStr,
        date_ymd: DateLike
    ) -> Dict[str, Dict]:
        """
        ★新メソッド★
        target_id と date_ymd の２つを指定して、
        その日付に対応するすべての message_id の投票内容を取得する。

        返り値：
        {
            "message_id1": {
                "thread_id": "...",
                "favorite": {...},
                "circle": {...},
                "cross": {...},
                "caution": {...},
            },
            "message_id2": {...},
            ...
        }
        """
        async def runner():
            return await self._get_all_for_target_date(str(target_id), str(date_ymd))
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging] get_all_for_target_date queue error: {e}", exc_info=True)
            return {}

    async def _get_all_for_target_date(
        self,
        target_id: str,
        date_ymd: str,
    ) -> Dict[str, Dict]:
        result: Dict[str, Dict] = {}

        target_doc_ref = self.db.collection(self.root).document(target_id)

        # message_id ごとのサブコレクションを列挙
        async for msg_subcol in target_doc_ref.collections():
            message_id = msg_subcol.id

            # date_ymd ドキュメントのみ取得
            day_doc_ref = msg_subcol.document(date_ymd)
            snap = await day_doc_ref.get()

            if not snap or not snap.exists:
                continue

            data = snap.to_dict() or {}

            result[message_id] = {
                "thread_id": data.get("thread_id"),
                "favorite": dict(data.get("favorite", {}) or {}),
                "circle": dict(data.get("circle", {}) or {}),
                "cross": dict(data.get("cross", {}) or {}),
                "caution": dict(data.get("caution", {}) or {}),
            }

        return result
