import logging
from typing import Dict, Optional, Tuple, Union, Any
from datetime import datetime

from google.cloud.firestore_v1 import AsyncClient
from google.cloud import firestore_v1 as firestore  # noqa: F401  # 将来の拡張用に残しておく

from configs.google_setup import client
from queuemanager.google.firestore import firestore_queue
from firestores.base import FirestoreBase

from discord import User

logger = logging.getLogger(__name__)

IntStr = Union[int, str]
DateLike = Union[str, datetime]


class FS_Judging_Temp(FirestoreBase):
    ROOT_COLLECTION = "Judging_Temp"
    CATEGORY_KEYS = ("circle", "cross", "caution")

    def __init__(
        self,
        root_collection: str = "Judging_Temp",
        queue_manager=firestore_queue,
    ):
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
        if not category_map:
            return "0"

        numeric_keys = []
        for key in category_map.keys():
            try:
                numeric_keys.append(int(key))
            except (TypeError, ValueError):
                continue

        if not numeric_keys:
            return str(len(category_map))

        return str(max(numeric_keys) + 1)

    def _day_doc(self, target_id: str, message_id: str, date_ymd: str):
        return (
            self.db.collection(self.root)
            .document(target_id)
            .collection(message_id)
            .document(date_ymd)
        )

    def _normalize_date_ymd(self, value: DateLike | None) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y%m%d")
        if value is None:
            return "None"
        text = str(value).strip()
        return text or "None"

    @staticmethod
    def _pick_non_empty(*values) -> Optional[str]:
        for value in values:
            if value is None:
                continue

            text = str(value).strip()
            if text:
                return text

        return None

    @staticmethod
    def _safe_int(value: Any, default: int = -1) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return default

    @staticmethod
    def _normalize_category_map(category_map: Dict | None) -> Dict[str, Dict]:
        result: Dict[str, Dict] = {}

        if not isinstance(category_map, dict):
            return result

        for idx, entry in category_map.items():
            if not isinstance(entry, dict):
                continue

            user_id = str(entry.get("user_id") or "").strip()
            if not user_id:
                continue

            payload = {
                "user_id": user_id,
                "user_name": str(entry.get("user_name") or "").strip(),
            }

            if "comment" in entry:
                payload["comment"] = str(entry.get("comment") or "").strip()

            result[str(idx)] = payload

        return result

    @staticmethod
    def _reindex_category_map(category_map: Dict[str, Dict]) -> Dict[str, Dict]:
        reindexed: Dict[str, Dict] = {}

        sorted_items = sorted(
            category_map.items(),
            key=lambda item: FS_Judging_Temp._safe_int(item[0], default=10**9),
        )

        for new_idx, (_, payload) in enumerate(sorted_items):
            reindexed[str(new_idx)] = payload

        return reindexed

    @classmethod
    def _merge_category_entries(
        cls,
        base_map: Dict[str, Dict],
        incoming_map: Dict[str, Dict],
    ) -> Dict[str, Dict]:
        merged_by_user: Dict[str, Dict] = {}

        def ingest(source: Dict[str, Dict]):
            normalized = cls._normalize_category_map(source)

            for _, entry in normalized.items():
                user_id = str(entry.get("user_id") or "").strip()
                if not user_id:
                    continue

                user_name = str(entry.get("user_name") or "").strip()
                comment_exists = "comment" in entry
                comment = str(entry.get("comment") or "").strip()

                old = merged_by_user.get(user_id)
                if old is None:
                    payload = {
                        "user_id": user_id,
                        "user_name": user_name,
                    }
                    if comment_exists:
                        payload["comment"] = comment
                    merged_by_user[user_id] = payload
                    continue

                old_name = str(old.get("user_name") or "").strip()
                old_comment = str(old.get("comment") or "").strip()

                if not old_name and user_name:
                    old["user_name"] = user_name

                if comment_exists and comment and not old_comment:
                    old["comment"] = comment
                elif comment_exists and "comment" not in old:
                    old["comment"] = comment

        ingest(base_map)
        ingest(incoming_map)

        temp_result: Dict[str, Dict] = {}
        for idx, user_id in enumerate(sorted(merged_by_user.keys(), key=lambda x: cls._safe_int(x, default=10**18))):
            temp_result[str(idx)] = merged_by_user[user_id]

        return temp_result

    async def _iter_all_docs_for_target(self, target_id: str) -> list[Dict[str, Any]]:
        docs: list[Dict[str, Any]] = []

        target_doc_ref = self.db.collection(self.root).document(target_id)

        async for msg_subcol in target_doc_ref.collections():
            message_id = str(msg_subcol.id)

            async for snap in msg_subcol.stream():
                if not snap.exists:
                    continue

                data = snap.to_dict() or {}
                docs.append(
                    {
                        "message_id": message_id,
                        "date_ymd": str(snap.id),
                        "admin_thread_id": data.get("admin_thread_id"),
                        "user_thread_id": data.get("user_thread_id"),
                        "user_message_id": data.get("user_message_id"),
                        "circle": dict(data.get("circle", {}) or {}),
                        "cross": dict(data.get("cross", {}) or {}),
                        "caution": dict(data.get("caution", {}) or {}),
                    }
                )

        return docs

    async def _delete_message_subcollection_if_empty(self, target_id: str, message_id: str) -> bool:
        try:
            msg_col_ref = (
                self.db.collection(self.root)
                .document(target_id)
                .collection(message_id)
            )

            async for snap in msg_col_ref.stream():
                if snap.exists:
                    return False

            # Firestore は空コレクション自体は実体を持たないので、何もする必要はない
            return True

        except Exception as e:
            logger.error(
                "[FS_Judging_Temp] _delete_message_subcollection_if_empty failed: %s",
                e,
            )
            return False

    async def _load_doc(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
    ) -> Tuple[Dict, Dict, Dict, Optional[str], Optional[str], bool]:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        snap = await doc_ref.get()

        if not snap or not snap.exists:
            logger.warning(f"Document not found: {target_id} - {message_id} - {date_ymd}")
            return {}, {}, {}, None, None, False

        data = snap.to_dict() or {}
        return (
            dict(data.get("circle", {}) or {}),
            dict(data.get("cross", {}) or {}),
            dict(data.get("caution", {}) or {}),
            data.get("admin_thread_id"),
            data.get("user_thread_id"),
            True,
        )

    async def _save_entry(
        self,
        *,
        target_id: str,
        message_id: str,
        date_ymd: str,
        admin_thread_id: Optional[str],
        user_thread_id: Optional[str],
        circle: Dict,
        cross: Dict,
        caution: Dict,
        user_message_id: Optional[str] = None,
    ) -> str:
        try:
            doc_ref = self._day_doc(target_id, message_id, date_ymd)

            data = {
                "circle": circle,
                "cross": cross,
                "caution": caution,
            }

            if admin_thread_id is not None:
                data["admin_thread_id"] = str(admin_thread_id)

            if user_thread_id is not None:
                data["user_thread_id"] = str(user_thread_id)

            if user_message_id is not None:
                data["user_message_id"] = str(user_message_id)

            await doc_ref.set(data, merge=False)
            return "ok"

        except Exception as e:
            logger.error(f"Error in _save_entry: {e}")
            return "error_occurred"

    async def _copy_doc(
        self,
        *,
        target_id: str,
        old_message_id: str,
        old_date_ymd: str,
        new_message_id: str,
        new_date_ymd: str,
        user_thread_id: str | None = None,
        user_message_id: str | None = None,
        delete_old: bool = True,
    ) -> str:
        old_doc_ref = self._day_doc(target_id, old_message_id, old_date_ymd)
        new_doc_ref = self._day_doc(target_id, new_message_id, new_date_ymd)

        old_snap = await old_doc_ref.get()
        if not old_snap or not old_snap.exists:
            return "not_found"

        old_data = old_snap.to_dict() or {}

        admin_thread_id = (
            old_data.get("admin_thread_id")
            or old_data.get("thread_id")
        )

        new_data = {
            "admin_thread_id": admin_thread_id,
            "user_thread_id": str(user_thread_id) if user_thread_id is not None else old_data.get("user_thread_id"),
            "user_message_id": str(user_message_id) if user_message_id is not None else old_data.get("user_message_id"),
            "circle": dict(old_data.get("circle", {}) or {}),
            "cross": dict(old_data.get("cross", {}) or {}),
            "caution": dict(old_data.get("caution", {}) or {}),
        }

        await new_doc_ref.set(new_data, merge=False)

        if delete_old:
            await old_doc_ref.delete()

        return "migrated"

    # ------------- Read -------------

    async def exists(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> bool:
        async def runner():
            return await self._exists(str(target_id), str(message_id), self._normalize_date_ymd(date_ymd))
        try:
            return await self._run(runner) or False
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] exists queue error: {e}", exc_info=True)
            return False

    async def _exists(self, target_id: str, message_id: str, date_ymd: str) -> bool:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        snap = await doc_ref.get()
        return snap.exists if snap else False

    async def get_entry(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> Dict[str, Dict]:
        async def runner():
            return await self._get_entry(str(target_id), str(message_id), self._normalize_date_ymd(date_ymd))
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] get_entry queue error: {e}", exc_info=True)
            return {}

    async def _get_entry(self, target_id: str, message_id: str, date_ymd: str) -> Dict[str, Dict]:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        snap = await doc_ref.get()
        if not snap or not snap.exists:
            return {}

        data = snap.to_dict() or {}
        return {
            "admin_thread_id": data.get("admin_thread_id"),
            "user_thread_id": data.get("user_thread_id"),
            "user_message_id": data.get("user_message_id"),
            "circle": dict(data.get("circle", {}) or {}),
            "cross": dict(data.get("cross", {}) or {}),
            "caution": dict(data.get("caution", {}) or {}),
        }

    async def get_category(
        self,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        category: str,
    ) -> Dict:
        async def runner():
            return await self._get_category(
                str(target_id), str(message_id), self._normalize_date_ymd(date_ymd), category
            )
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] get_category queue error: {e}", exc_info=True)
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
            raise ValueError("category must be one of circle, cross, caution")

        circle, cross, caution, _, _, _ = await self._load_doc(target_id, message_id, date_ymd)

        if category == "circle":
            return circle
        if category == "cross":
            return cross
        return caution

    # ------------- Write -------------

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
            return await self._set_vote(
                category, str(target_id), str(message_id), self._normalize_date_ymd(date_ymd), user, comment
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] set_vote queue error: {e}", exc_info=True)
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
        if category not in self.CATEGORY_KEYS:
            raise ValueError("category must be one of circle, cross, caution")

        user_name = getattr(user, "display_name", None) or getattr(user, "name", str(user.id))
        user_id = str(user.id)

        return await self._set_vote_category(
            target_id=target_id,
            message_id=message_id,
            date_ymd=date_ymd,
            category=category,
            user_id=user_id,
            user_name=user_name,
            comment=comment,
        )

    async def _set_vote_category(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        category: str,
        user_id: str,
        user_name: str,
        comment: Optional[str] = None,
    ) -> str:
        try:
            circle, cross, caution, admin_thread_id, user_thread_id, _ = await self._load_doc(
                target_id,
                message_id,
                date_ymd,
            )

            circle_idx = self._find_user_index(circle, user_id)
            cross_idx = self._find_user_index(cross, user_id)
            caution_idx = self._find_user_index(caution, user_id)

            if category == "circle":
                current_idx = circle_idx
                current_map = circle
            elif category == "cross":
                current_idx = cross_idx
                current_map = cross
            else:
                current_idx = caution_idx
                current_map = caution

            norm_comment = (comment or "").strip()

            if current_idx is not None:
                if category == "circle":
                    current_map.pop(current_idx, None)

                    save_result = await self._save_entry(
                        target_id=target_id,
                        message_id=message_id,
                        date_ymd=date_ymd,
                        admin_thread_id=admin_thread_id,
                        user_thread_id=user_thread_id,
                        circle=circle,
                        cross=cross,
                        caution=caution,
                    )
                    if save_result == "error_occurred":
                        return "error_occurred"

                    return "remove"

                old_comment = (current_map[current_idx].get("comment") or "").strip()
                if old_comment == norm_comment:
                    return "no_change"

                current_map[current_idx] = {
                    "user_id": user_id,
                    "user_name": user_name,
                    "comment": norm_comment,
                }

                save_result = await self._save_entry(
                    target_id=target_id,
                    message_id=message_id,
                    date_ymd=date_ymd,
                    admin_thread_id=admin_thread_id,
                    user_thread_id=user_thread_id,
                    circle=circle,
                    cross=cross,
                    caution=caution,
                )
                if save_result == "error_occurred":
                    return "error_occurred"

                return "change"

            removed_from_other = any(idx is not None for idx in [circle_idx, cross_idx, caution_idx])

            if circle_idx is not None:
                circle.pop(circle_idx, None)
            if cross_idx is not None:
                cross.pop(cross_idx, None)
            if caution_idx is not None:
                caution.pop(caution_idx, None)

            payload = {
                "user_id": user_id,
                "user_name": user_name,
            }

            if category in ("cross", "caution"):
                payload["comment"] = norm_comment

            if category == "circle":
                new_idx = self._next_index(circle)
                circle[new_idx] = payload
            elif category == "cross":
                new_idx = self._next_index(cross)
                cross[new_idx] = payload
            else:
                new_idx = self._next_index(caution)
                caution[new_idx] = payload

            save_result = await self._save_entry(
                target_id=target_id,
                message_id=message_id,
                date_ymd=date_ymd,
                admin_thread_id=admin_thread_id,
                user_thread_id=user_thread_id,
                circle=circle,
                cross=cross,
                caution=caution,
            )
            if save_result == "error_occurred":
                return "error_occurred"

            return "change" if removed_from_other else "add"

        except Exception as e:
            logger.error(f"Error in _set_vote_category: {e}")
            return "error_occurred"

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
                str(target_id), str(message_id), self._normalize_date_ymd(date_ymd), category, str(user_id)
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] remove_from_category queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _remove_from_category(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        category: str,
        user_id: str,
    ) -> str:
        category = category.lower()
        if category not in self.CATEGORY_KEYS:
            raise ValueError("category must be one of circle, cross, caution")

        circle, cross, caution, admin_thread_id, user_thread_id, exists = await self._load_doc(
            target_id, message_id, date_ymd
        )
        if not exists:
            return "not_found"

        removed = False

        if category == "circle":
            idx = self._find_user_index(circle, user_id)
            if idx is not None:
                circle.pop(idx, None)
                removed = True

        elif category == "cross":
            idx = self._find_user_index(cross, user_id)
            if idx is not None:
                cross.pop(idx, None)
                removed = True

        else:
            idx = self._find_user_index(caution, user_id)
            if idx is not None:
                caution.pop(idx, None)
                removed = True

        if not removed:
            return "not_found"

        save_result = await self._save_entry(
            target_id=target_id,
            message_id=message_id,
            date_ymd=date_ymd,
            admin_thread_id=admin_thread_id,
            user_thread_id=user_thread_id,
            circle=circle,
            cross=cross,
            caution=caution,
        )
        if save_result == "error_occurred":
            return "error_occurred"

        return "removed"

    async def clear_all_categories(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> str:
        async def runner():
            return await self._clear_all_categories(
                str(target_id), str(message_id), self._normalize_date_ymd(date_ymd)
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] clear_all_categories queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _clear_all_categories(self, target_id: str, message_id: str, date_ymd: str) -> str:
        _, _, _, admin_thread_id, user_thread_id, exists = await self._load_doc(
            target_id, message_id, date_ymd
        )
        if not exists:
            return "not_found"

        save_result = await self._save_entry(
            target_id=target_id,
            message_id=message_id,
            date_ymd=date_ymd,
            admin_thread_id=admin_thread_id,
            user_thread_id=user_thread_id,
            circle={},
            cross={},
            caution={},
        )
        if save_result == "error_occurred":
            return "error_occurred"

        return "cleared"

    async def clear_message_date(self, target_id: IntStr, message_id: IntStr, date_ymd: DateLike) -> str:
        async def runner():
            return await self._clear_message_date(
                str(target_id), str(message_id), self._normalize_date_ymd(date_ymd)
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] clear_message_date queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _clear_message_date(self, target_id: str, message_id: str, date_ymd: str) -> str:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)
        await doc_ref.delete()
        return "deleted"

    async def init_day_entry(
        self,
        target_id: IntStr,
        message_id: IntStr,
        date_ymd: DateLike,
        admin_thread_id: IntStr,
        user_thread_id: IntStr,
        overwrite: bool = False,
    ) -> str:
        async def runner():
            return await self._init_day_entry(
                str(target_id),
                str(message_id),
                self._normalize_date_ymd(date_ymd),
                str(admin_thread_id),
                str(user_thread_id),
                overwrite,
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] init_day_entry queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _init_day_entry(
        self,
        target_id: str,
        message_id: str,
        date_ymd: str,
        admin_thread_id: str,
        user_thread_id: str,
        overwrite: bool = False,
    ) -> str:
        doc_ref = self._day_doc(target_id, message_id, date_ymd)

        snap = await doc_ref.get()
        if snap and snap.exists and not overwrite:
            return "exists"

        data = {
            "admin_thread_id": admin_thread_id,
            "user_thread_id": user_thread_id,
            "circle": {},
            "cross": {},
            "caution": {},
        }

        await doc_ref.set(data, merge=not overwrite)
        return "initialized"

    async def get_all_for_target_date(
        self,
        target_id: IntStr,
        date_ymd: DateLike
    ) -> Dict[str, Dict]:
        async def runner():
            return await self._get_all_for_target_date(str(target_id), self._normalize_date_ymd(date_ymd))
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] get_all_for_target_date queue error: {e}", exc_info=True)
            return {}

    async def _get_all_for_target_date(
        self,
        target_id: str,
        date_ymd: str,
    ) -> Dict[str, Dict]:
        result: Dict[str, Dict] = {}

        target_doc_ref = self.db.collection(self.root).document(target_id)

        async for msg_subcol in target_doc_ref.collections():
            message_id = msg_subcol.id

            day_doc_ref = msg_subcol.document(date_ymd)
            snap = await day_doc_ref.get()

            if not snap or not snap.exists:
                continue

            data = snap.to_dict() or {}

            result[message_id] = {
                "admin_thread_id": data.get("admin_thread_id"),
                "user_thread_id": data.get("user_thread_id"),
                "user_message_id": data.get("user_message_id"),
                "circle": dict(data.get("circle", {}) or {}),
                "cross": dict(data.get("cross", {}) or {}),
                "caution": dict(data.get("caution", {}) or {}),
            }

        return result

    async def get_latest_entry_for_target(self, target_id: IntStr) -> Dict[str, Dict]:
        async def runner():
            return await self._get_latest_entry_for_target(str(target_id))
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] get_latest_entry_for_target queue error: {e}", exc_info=True)
            return {}

    async def _get_latest_entry_for_target(self, target_id: str) -> Dict[str, Dict]:
        latest_doc: dict | None = None

        target_doc_ref = self.db.collection(self.root).document(target_id)

        async for msg_subcol in target_doc_ref.collections():
            message_id = str(msg_subcol.id)

            async for snap in msg_subcol.stream():
                if not snap.exists:
                    continue

                date_ymd = str(snap.id)
                if date_ymd == "None":
                    continue

                data = snap.to_dict() or {}

                current = {
                    "message_id": message_id,
                    "date_ymd": date_ymd,
                    "admin_thread_id": data.get("admin_thread_id"),
                    "user_thread_id": data.get("user_thread_id"),
                    "user_message_id": data.get("user_message_id"),
                    "circle": dict(data.get("circle", {}) or {}),
                    "cross": dict(data.get("cross", {}) or {}),
                    "caution": dict(data.get("caution", {}) or {}),
                }

                if latest_doc is None:
                    latest_doc = current
                    continue

                current_key = (
                    self._safe_int(current["message_id"]),
                    current["date_ymd"],
                )
                latest_key = (
                    self._safe_int(latest_doc["message_id"]),
                    latest_doc["date_ymd"],
                )

                if current_key > latest_key:
                    latest_doc = current

        return latest_doc or {}

    async def migrate_message_entry(
        self,
        *,
        target_id: IntStr,
        old_message_id: IntStr,
        new_message_id: IntStr,
        date_ymd: DateLike,
        old_date_ymd: DateLike | None = None,
        user_thread_id: IntStr,
        user_message_id: IntStr | None = None,
        delete_old: bool = True,
    ) -> str:
        async def runner():
            return await self._migrate_message_entry(
                target_id=str(target_id),
                old_message_id=str(old_message_id),
                new_message_id=str(new_message_id),
                date_ymd=date_ymd,
                old_date_ymd=old_date_ymd,
                user_thread_id=user_thread_id,
                user_message_id=user_message_id,
                delete_old=delete_old,
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] migrate_message_entry queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _migrate_message_entry(
        self,
        *,
        target_id: str,
        old_message_id: str,
        new_message_id: str,
        date_ymd: DateLike,
        old_date_ymd: DateLike | None = None,
        user_thread_id: IntStr,
        user_message_id: IntStr | None = None,
        delete_old: bool = True,
    ) -> str:
        new_d_ymd = self._normalize_date_ymd(date_ymd)
        old_d_ymd = self._normalize_date_ymd(old_date_ymd if old_date_ymd is not None else date_ymd)
        user_th_id = str(user_thread_id)
        user_msg_id = str(user_message_id) if user_message_id is not None else None

        if old_message_id == new_message_id and old_d_ymd == new_d_ymd:
            return "same_message_id"

        result = await self._copy_doc(
            target_id=target_id,
            old_message_id=old_message_id,
            old_date_ymd=old_d_ymd,
            new_message_id=new_message_id,
            new_date_ymd=new_d_ymd,
            user_thread_id=user_th_id,
            user_message_id=user_msg_id,
            delete_old=delete_old,
        )
        return result

    async def repair_none_date_entry(
        self,
        *,
        target_id: IntStr,
        message_id: IntStr,
        correct_date_ymd: DateLike,
        delete_old: bool = True,
    ) -> str:
        async def runner():
            return await self._repair_none_date_entry(
                target_id=str(target_id),
                message_id=str(message_id),
                correct_date_ymd=correct_date_ymd,
                delete_old=delete_old,
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] repair_none_date_entry queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _repair_none_date_entry(
        self,
        *,
        target_id: str,
        message_id: str,
        correct_date_ymd: DateLike,
        delete_old: bool = True,
    ) -> str:
        new_d_ymd = self._normalize_date_ymd(correct_date_ymd)

        if new_d_ymd == "None":
            return "invalid_date_ymd"

        result = await self._copy_doc(
            target_id=target_id,
            old_message_id=message_id,
            old_date_ymd="None",
            new_message_id=message_id,
            new_date_ymd=new_d_ymd,
            delete_old=delete_old,
        )
        return result

    async def repair_none_date_entry_to_new_message(
        self,
        *,
        target_id: IntStr,
        old_message_id: IntStr,
        new_message_id: IntStr,
        correct_date_ymd: DateLike,
        user_thread_id: IntStr | None = None,
        user_message_id: IntStr | None = None,
        delete_old: bool = True,
    ) -> str:
        async def runner():
            return await self._repair_none_date_entry_to_new_message(
                target_id=str(target_id),
                old_message_id=str(old_message_id),
                new_message_id=str(new_message_id),
                correct_date_ymd=correct_date_ymd,
                user_thread_id=user_thread_id,
                user_message_id=user_message_id,
                delete_old=delete_old,
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] repair_none_date_entry_to_new_message queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _repair_none_date_entry_to_new_message(
        self,
        *,
        target_id: str,
        old_message_id: str,
        new_message_id: str,
        correct_date_ymd: DateLike,
        user_thread_id: IntStr | None = None,
        user_message_id: IntStr | None = None,
        delete_old: bool = True,
    ) -> str:
        new_d_ymd = self._normalize_date_ymd(correct_date_ymd)

        if new_d_ymd == "None":
            return "invalid_date_ymd"

        result = await self._copy_doc(
            target_id=target_id,
            old_message_id=old_message_id,
            old_date_ymd="None",
            new_message_id=new_message_id,
            new_date_ymd=new_d_ymd,
            user_thread_id=str(user_thread_id) if user_thread_id is not None else None,
            user_message_id=str(user_message_id) if user_message_id is not None else None,
            delete_old=delete_old,
        )
        return result

    async def find_none_date_entries_for_target(self, target_id: IntStr) -> Dict[str, Dict]:
        async def runner():
            return await self._find_none_date_entries_for_target(str(target_id))
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] find_none_date_entries_for_target queue error: {e}", exc_info=True)
            return {}

    async def _find_none_date_entries_for_target(self, target_id: str) -> Dict[str, Dict]:
        result: Dict[str, Dict] = {}

        target_doc_ref = self.db.collection(self.root).document(target_id)

        async for msg_subcol in target_doc_ref.collections():
            message_id = msg_subcol.id
            none_doc_ref = msg_subcol.document("None")
            snap = await none_doc_ref.get()

            if not snap or not snap.exists:
                continue

            data = snap.to_dict() or {}
            result[message_id] = {
                "admin_thread_id": data.get("admin_thread_id"),
                "user_thread_id": data.get("user_thread_id"),
                "user_message_id": data.get("user_message_id"),
                "circle": dict(data.get("circle", {}) or {}),
                "cross": dict(data.get("cross", {}) or {}),
                "caution": dict(data.get("caution", {}) or {}),
            }

        return result

    async def find_entry_by_message_id(
        self,
        *,
        target_id: IntStr,
        message_id: IntStr,
    ) -> dict:
        async def runner():
            return await self._find_entry_by_message_id(str(target_id), str(message_id))
        try:
            return await self._run(runner) or {}
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] find_entry_by_message_id queue error: {e}", exc_info=True)
            return {}

    async def _find_entry_by_message_id(self, target_id: str, message_id: str) -> dict:
        msg_col_ref = (
            self.db.collection(self.root)
            .document(target_id)
            .collection(message_id)
        )

        async for snap in msg_col_ref.stream():
            if not snap.exists:
                continue

            data = snap.to_dict() or {}
            return {
                "target_id": target_id,
                "message_id": message_id,
                "date_ymd": str(snap.id),
                "admin_thread_id": data.get("admin_thread_id"),
                "user_thread_id": data.get("user_thread_id"),
                "user_message_id": data.get("user_message_id"),
                "circle": dict(data.get("circle", {}) or {}),
                "cross": dict(data.get("cross", {}) or {}),
                "caution": dict(data.get("caution", {}) or {}),
            }

        return {}

    async def get_entry_by_target_and_admin_thread_id(
        self,
        target_id: int,
        admin_thread_id: int,
    ) -> dict | None:
        async def runner():
            return await self._get_entry_by_target_and_admin_thread_id(
                str(target_id), str(admin_thread_id)
            )
        try:
            result = await self._run(runner)
            # _run が None を返した場合は None のまま返す（デフォルト値 None）
            return result
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] get_entry_by_target_and_admin_thread_id queue error: {e}", exc_info=True)
            return None

    async def _get_entry_by_target_and_admin_thread_id(
        self,
        target_id: str,
        admin_thread_id: str,
    ) -> dict | None:
        target_doc_ref = self.db.collection(self.root).document(target_id)

        async for message_subcol in target_doc_ref.collections():
            message_id = message_subcol.id

            async for snap in message_subcol.stream():
                if not snap.exists:
                    continue

                data = snap.to_dict() or {}

                if str(data.get("admin_thread_id")) == admin_thread_id:
                    return {
                        "target_id": target_id,
                        "message_id": message_id,
                        "date_ymd": snap.id,
                        **data,
                    }

        return None

    # ------------- Repair / Rescue -------------

    async def unify_target_keep_latest_message(
        self,
        *,
        target_id: IntStr,
        delete_old: bool = True,
    ) -> dict:
        """
        指定 target_id 配下の全 message_id / date_ymd を走査し、
        date_ymd != "None" の中で最新の message_id + date_ymd を採用先にして、
        circle / cross / caution / thread系を統合する。

        優先順位:
        - 採用先ドキュメントの thread_id 類を最優先
        - 投票カテゴリ重複時は cross > caution > circle
        - 同一カテゴリ内の同一 user_id は、既存の非空 user_name / comment を優先して保持

        戻り値例:
        {
            "status": "ok",
            "target_id": "...",
            "target_message_id": "...",
            "target_date_ymd": "...",
            "scanned_docs": 4,
            "deleted_docs": 3,
        }
        """
        async def runner():
            return await self._unify_target_keep_latest_message(
                target_id=str(target_id), delete_old=delete_old
            )
        try:
            return await self._run(runner) or "error_occurred"
        except Exception as e:
            logger.error(f"[FS_Judging_Temp] unify_target_keep_latest_message queue error: {e}", exc_info=True)
            return "error_occurred"

    async def _unify_target_keep_latest_message(
        self,
        *,
        target_id: str,
        delete_old: bool = True,
    ) -> dict:
        try:
            scanned = await self._iter_all_docs_for_target(target_id)

            if not scanned:
                return {
                    "status": "not_found",
                    "target_id": target_id,
                    "scanned_docs": 0,
                    "deleted_docs": 0,
                }

            valid_docs = [
                doc for doc in scanned
                if str(doc.get("date_ymd")) != "None"
            ]

            if not valid_docs:
                return {
                    "status": "no_valid_date_doc",
                    "target_id": target_id,
                    "scanned_docs": len(scanned),
                    "deleted_docs": 0,
                }

            canonical = max(
                valid_docs,
                key=lambda doc: (
                    self._safe_int(doc.get("message_id")),
                    str(doc.get("date_ymd")),
                ),
            )

            ordered_docs = [canonical] + [
                doc for doc in scanned
                if not (
                    str(doc.get("message_id")) == str(canonical.get("message_id"))
                    and str(doc.get("date_ymd")) == str(canonical.get("date_ymd"))
                )
            ]

            merged_circle: Dict[str, Dict] = {}
            merged_cross: Dict[str, Dict] = {}
            merged_caution: Dict[str, Dict] = {}

            admin_thread_id = None
            user_thread_id = None
            user_message_id = None

            for doc in ordered_docs:
                admin_thread_id = self._pick_non_empty(
                    admin_thread_id,
                    doc.get("admin_thread_id"),
                )
                user_thread_id = self._pick_non_empty(
                    user_thread_id,
                    doc.get("user_thread_id"),
                )
                user_message_id = self._pick_non_empty(
                    user_message_id,
                    doc.get("user_message_id"),
                )

                merged_circle = self._merge_category_entries(
                    merged_circle,
                    doc.get("circle", {}) or {},
                )
                merged_cross = self._merge_category_entries(
                    merged_cross,
                    doc.get("cross", {}) or {},
                )
                merged_caution = self._merge_category_entries(
                    merged_caution,
                    doc.get("caution", {}) or {},
                )

            cross_user_ids = {
                str(v.get("user_id"))
                for v in merged_cross.values()
                if isinstance(v, dict) and v.get("user_id")
            }
            caution_user_ids = {
                str(v.get("user_id"))
                for v in merged_caution.values()
                if isinstance(v, dict) and v.get("user_id")
            }

            filtered_circle: Dict[str, Dict] = {}
            for _, entry in merged_circle.items():
                uid = str(entry.get("user_id") or "")
                if not uid:
                    continue
                if uid in cross_user_ids or uid in caution_user_ids:
                    continue
                filtered_circle[str(len(filtered_circle))] = entry

            filtered_caution: Dict[str, Dict] = {}
            for _, entry in merged_caution.items():
                uid = str(entry.get("user_id") or "")
                if not uid:
                    continue
                if uid in cross_user_ids:
                    continue
                filtered_caution[str(len(filtered_caution))] = entry

            filtered_cross = self._reindex_category_map(merged_cross)
            filtered_circle = self._reindex_category_map(filtered_circle)
            filtered_caution = self._reindex_category_map(filtered_caution)

            save_result = await self._save_entry(
                target_id=target_id,
                message_id=str(canonical["message_id"]),
                date_ymd=str(canonical["date_ymd"]),
                admin_thread_id=admin_thread_id,
                user_thread_id=user_thread_id,
                circle=filtered_circle,
                cross=filtered_cross,
                caution=filtered_caution,
                user_message_id=user_message_id,
            )
            if save_result == "error_occurred":
                return {
                    "status": "error_occurred",
                    "target_id": target_id,
                    "scanned_docs": len(scanned),
                    "deleted_docs": 0,
                }

            deleted_docs = 0

            if delete_old:
                for doc in scanned:
                    doc_message_id = str(doc.get("message_id"))
                    doc_date_ymd = str(doc.get("date_ymd"))

                    if (
                        doc_message_id == str(canonical["message_id"])
                        and doc_date_ymd == str(canonical["date_ymd"])
                    ):
                        continue

                    delete_result = await self._clear_message_date(
                        target_id=target_id,
                        message_id=doc_message_id,
                        date_ymd=doc_date_ymd,
                    )
                    if delete_result == "deleted":
                        deleted_docs += 1
                        await self._delete_message_subcollection_if_empty(
                            target_id=target_id,
                            message_id=doc_message_id,
                        )

            return {
                "status": "ok",
                "target_id": target_id,
                "target_message_id": str(canonical["message_id"]),
                "target_date_ymd": str(canonical["date_ymd"]),
                "admin_thread_id": admin_thread_id,
                "user_thread_id": user_thread_id,
                "user_message_id": user_message_id,
                "scanned_docs": len(scanned),
                "deleted_docs": deleted_docs,
                "circle_count": len(filtered_circle),
                "cross_count": len(filtered_cross),
                "caution_count": len(filtered_caution),
            }

        except Exception as e:
            logger.error(
                "[FS_Judging_Temp] _unify_target_keep_latest_message failed: %s",
                e,
            )
            return {
                "status": "error_occurred",
                "target_id": target_id,
                "scanned_docs": 0,
                "deleted_docs": 0,
            }
