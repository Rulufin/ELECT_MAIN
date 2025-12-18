import logging
from typing import Dict, Optional, Tuple, Union
from datetime import datetime
from zoneinfo import ZoneInfo

from google.cloud.firestore_v1 import AsyncClient
from google.cloud import firestore_v1 as firestore  # noqa: F401  # 将来の拡張用に残しておく

from configs.google_setup import client
from queuemanagers.google.fs_queuemanager import firestore_queue

from discord import User

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateLike = Union[str, datetime]

class FS_Judging:
    ROOT_COLLECTION = "Judging"
    CATEGORY_KEYS = ("circle", "triangle", "cross", "caution")

    def __init__(
        self,
        root_collection: str = "Judging",
        queue_manager=firestore_queue,  # 型: QueueManager_FireStore インスタンス想定
    ):
        # Firestoreクライアント
        if not isinstance(client.firestore_db, AsyncClient):
            raise TypeError("client.firestore_db must be an AsyncClient (async Firestore).")
        self.db: AsyncClient = client.firestore_db
        self.root = root_collection

        # Firestoreキュー
        self.queue = queue_manager

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

    # --- Firestore操作をキュー経由にする小ヘルパー群 ---
    
    async def _q_get(self, doc_ref):
        async def get_doc():
            return await doc_ref.get()

        try:
            return await self.queue.enqueue(get_doc)
        except Exception as e:
            logger.error(f"Error in _q_get: {e}")
            return None  # Return None if there's an error

    async def _q_set(self, doc_ref, data: Dict, merge: bool = True):
        async def set_doc():
            return await doc_ref.set(data, merge=merge)

        try:
            return await self.queue.enqueue(set_doc)
        except Exception as e:
            logger.error(f"Error in _q_set: {e}")
            return "error_occurred"  # Return error message

    async def _q_delete(self, doc_ref):
        async def delete_doc():
            return await doc_ref.delete()

        try:
            return await self.queue.enqueue(delete_doc)
        except Exception as e:
            logger.error(f"Error in _q_delete: {e}")
            return "error_occurred"  # Return error message

    async def _load_maps(
        self, target_id: str, message_id: str, date_ymd: str
    ) -> Tuple[Dict, Dict, Dict, Dict, bool]:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        snap = await self._q_get(doc_ref)
        if not snap or not snap.exists:
            logger.warning(f"Document not found: {target_id} - {message_id} - {date_ymd}")
            return {}, {}, {}, {}, False
        data = snap.to_dict() or {}
        return (
            dict(data.get("circle", {}) or {}),
            dict(data.get("triangle", {}) or {}),
            dict(data.get("cross", {}) or {}),
            dict(data.get("caution", {}) or {}),
            True,
        )

    # ------------- Read -------------
    
    async def exists(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> bool:
        try:
            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)

            doc_ref = self._day_doc(t_id, m_id, d_ymd)
            snap = await self._q_get(doc_ref)
            return snap.exists if snap else False
        except Exception as e:
            logger.error(f"Error in exists check: {e}")
            return False

    async def get_entry(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> Dict[str, Dict]:
        try:
            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)

            circle, triangle, cross, caution, _ = await self._load_maps(t_id, m_id, d_ymd)
            return {
                "circle": circle,
                "triangle": triangle,
                "cross": cross,
                "caution": caution,
            }
        except Exception as e:
            logger.error(f"Error in get_entry: {e}")
            return {}

    async def get_category(
        self,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        category: str,
    ) -> Dict:
        try:
            category = category.lower()
            if category not in self.CATEGORY_KEYS:
                raise ValueError("category must be one of circle, triangle, cross, caution")

            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)

            circle, triangle, cross, caution, _ = await self._load_maps(t_id, m_id, d_ymd)
            if category == "circle":
                return circle
            if category == "triangle":
                return triangle
            if category == "cross":
                return cross
            return caution  # caution
        except Exception as e:
            logger.error(f"Error in get_category: {e}")
            return {}

    # ------------- Write (circle/triangle/cross toggle + move exclusivity) -------------
    
    async def set_vote(
        self,
        category: str,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        user: Optional[User],
        comment: Optional[str] = None,
    ) -> str:
        try:
            if user is None:
                raise ValueError("user must not be None")

            category = category.lower()
            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)

            # display_name が無いタイプ（純 User）の場合も考慮
            user_name = getattr(user, "display_name", None) or getattr(user, "name", str(user.id))
            user_id = str(user.id)

            if category in ("circle", "triangle", "cross"):
                return await self._set_simple_category(
                    target_id=t_id,
                    message_id=m_id,
                    date_ymd=d_ymd,
                    category=category,
                    user_id=user_id,
                    user_name=user_name,
                )

            elif category == "caution":
                return await self.set_caution(
                    target_id=t_id,
                    message_id=m_id,
                    date_ymd=d_ymd,
                    user_id=user_id,
                    user_name=user_name,
                    comment=comment,
                )

            raise ValueError("category must be one of circle, triangle, cross, caution")
        
        except Exception as e:
            logger.error(f"Error in set_vote: {e}")
            return "error_occurred"

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

            circle, triangle, cross, caution, _ = await self._load_maps(target_id, message_id, date_ymd)

            # 現在どのカテゴリにいるか
            circle_idx = self._find_user_index(circle, user_id)
            triangle_idx = self._find_user_index(triangle, user_id)
            cross_idx = self._find_user_index(cross, user_id)
            caution_idx = self._find_user_index(caution, user_id)

            # 同じカテゴリを押した → 取り消し
            if category == "circle":
                current_idx = circle_idx
                current_map = circle
            elif category == "triangle":
                current_idx = triangle_idx
                current_map = triangle
            else:  # "cross"
                current_idx = cross_idx
                current_map = cross

            if current_idx is not None:
                current_map.pop(current_idx, None)
                await self._q_set(
                    doc_ref,
                    {
                        "circle": circle,
                        "triangle": triangle,
                        "cross": cross,
                        "caution": caution,
                    },
                    merge=True,
                )
                return "remove"

            # それ以外 → 排他（他カテゴリから削除）
            removed_from_other = any(
                idx is not None
                for idx in [circle_idx, triangle_idx, cross_idx, caution_idx]
            )

            if circle_idx is not None:
                circle.pop(circle_idx)
            if triangle_idx is not None:
                triangle.pop(triangle_idx)
            if cross_idx is not None:
                cross.pop(cross_idx)
            if caution_idx is not None:
                caution.pop(caution_idx)

            # 新規追加
            payload = {"user_id": user_id, "user_name": user_name}
            if category == "circle":
                new_idx = self._next_index(circle)
                circle[new_idx] = payload
            elif category == "triangle":
                new_idx = self._next_index(triangle)
                triangle[new_idx] = payload
            else:
                new_idx = self._next_index(cross)
                cross[new_idx] = payload

            await self._q_set(
                doc_ref,
                {
                    "circle": circle,
                    "triangle": triangle,
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
        try:
            doc_ref = self._day_doc(target_id, message_id, date_ymd)
            circle, triangle, cross, caution, _ = await self._load_maps(target_id, message_id, date_ymd)

            norm = (comment or "").strip()

            # 各カテゴリでの index
            circle_idx = self._find_user_index(circle, user_id)
            triangle_idx = self._find_user_index(triangle, user_id)
            cross_idx = self._find_user_index(cross, user_id)
            caution_idx = self._find_user_index(caution, user_id)

            # コメント空白 → CAUTION のみ削除
            if norm == "":
                if caution_idx is not None:
                    caution.pop(caution_idx, None)
                    await self._q_set(doc_ref, {"caution": caution}, merge=True)
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
                await self._q_set(doc_ref, {"caution": caution}, merge=True)
                return "change"

            # 他カテゴリ → CAUTIONに移動（排他）
            removed_from_other = any(
                idx is not None for idx in [circle_idx, triangle_idx, cross_idx]
            )

            if circle_idx is not None:
                circle.pop(circle_idx)
            if triangle_idx is not None:
                triangle.pop(triangle_idx)
            if cross_idx is not None:
                cross.pop(cross_idx)

            new_idx = self._next_index(caution)
            caution[new_idx] = {
                "user_id": user_id,
                "user_name": user_name,
                "comment": norm,
            }

            await self._q_set(
                doc_ref,
                {
                    "circle": circle,
                    "triangle": triangle,
                    "cross": cross,
                    "caution": caution,
                },
                merge=True,
            )

            return "change" if removed_from_other else "add"
        except Exception as e:
            logger.error(f"Error in set_caution: {e}")
            return "error_occurred"

    # ------------- Removal / Clear -------------
    
    async def remove_from_category(
        self,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        category: str,
        user_id: IntStr,
    ) -> None:
        try:
            category = category.lower()
            if category not in self.CATEGORY_KEYS:
                raise ValueError("category must be one of circle, triangle, cross, caution")

            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)
            u_id = str(user_id)

            doc_ref = self._day_doc(t_id, m_id, d_ymd)
            circle, triangle, cross, caution, _ = await self._load_maps(t_id, m_id, d_ymd)

            if category == "circle":
                idx = self._find_user_index(circle, u_id)
                if idx is not None:
                    circle.pop(idx, None)
                    await self._q_set(doc_ref, {"circle": circle}, merge=True)
                return

            if category == "triangle":
                idx = self._find_user_index(triangle, u_id)
                if idx is not None:
                    triangle.pop(idx, None)
                    await self._q_set(doc_ref, {"triangle": triangle}, merge=True)
                return

            if category == "cross":
                idx = self._find_user_index(cross, u_id)
                if idx is not None:
                    cross.pop(idx, None)
                    await self._q_set(doc_ref, {"cross": cross}, merge=True)
                return

            # caution
            idx = self._find_user_index(caution, u_id)
            if idx is not None:
                caution.pop(idx, None)
                await self._q_set(doc_ref, {"caution": caution}, merge=True)
        except Exception as e:
            logger.error(f"Error in remove_from_category: {e}")
            return "error_occurred"

    async def clear_all_categories(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> None:
        try:
            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)

            doc_ref = self._day_doc(t_id, m_id, d_ymd)
            await self._q_set(
                doc_ref,
                {
                    "circle": {},
                    "triangle": {},
                    "cross": {},
                    "caution": {},
                },
                merge=True,
            )
        except Exception as e:
            logger.error(f"Error in clear_all_categories: {e}")
            return "error_occurred"

    async def clear_message_date(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> None:
        try:
            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)

            doc_ref = self._day_doc(t_id, m_id, d_ymd)
            await self._q_delete(doc_ref)
        except Exception as e:
            logger.error(f"Error in clear_message_date: {e}")
            return "error_occurred"

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
            - circle / triangle / cross / caution は空の map
          
        overwrite=True の場合、既存ドキュメントを完全上書きする。
        overwrite=False の場合、既に存在していたら何もせず "exists" を返す。
        """
        try:
            t_id = str(target_id)
            m_id = str(message_id)
            d_ymd = str(date_ymd)
            th_id = str(thread_id)

            doc_ref = self._day_doc(t_id, m_id, d_ymd)

            snap = await self._q_get(doc_ref)
            if snap and snap.exists and not overwrite:
                return "exists"

            data = {
                "thread_id": th_id,
                "circle": {},
                "triangle": {},
                "cross": {},
                "caution": {},
            }

            # overwrite の場合 merge=False にして完全上書き
            await self._q_set(doc_ref, data, merge=not overwrite)

            return "initialized"

        except Exception as e:
            logger.error(f"Error in init_day_entry: {e}")
            return "error_occurred"

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
                "circle": {...},
                "triangle": {...},
                "cross": {...},
                "caution": {...},
            },
            "message_id2": {...},
            ...
        }
        """
        t_id = str(target_id)
        d_ymd = str(date_ymd)

        result: Dict[str, Dict] = {}

        try:
            target_doc_ref = self.db.collection(self.root).document(t_id)

            # message_id ごとのサブコレクションを列挙
            async for msg_subcol in target_doc_ref.collections():
                message_id = msg_subcol.id

                # date_ymd ドキュメントのみ取得
                day_doc_ref = msg_subcol.document(d_ymd)
                snap = await self._q_get(day_doc_ref)

                if not snap or not snap.exists:
                    continue

                data = snap.to_dict() or {}

                result[message_id] = {
                    "thread_id": data.get("thread_id"),
                    "circle": dict(data.get("circle", {}) or {}),
                    "triangle": dict(data.get("triangle", {}) or {}),
                    "cross": dict(data.get("cross", {}) or {}),
                    "caution": dict(data.get("caution", {}) or {}),
                }

        except Exception as e:
            logger.error(f"Error in get_all_for_target_date: {e}")

        return result
