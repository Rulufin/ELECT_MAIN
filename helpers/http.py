# discord_http.py
import aiohttp
import logging
from typing import Any, Dict, Optional, Tuple, Sequence, List

from utils.ids import MAIN_SERVER_ID, APPLICATION_ID     # 既存定義を利用
from queuemanagers.discord.dc_ququemanager import discord_queue          # QueueManager_Discord インスタンス（enqueue/enqueue_fastlaneあり）

logger = logging.getLogger(__name__)
BASE_URL = "https://discord.com/api/v10"


# ─────────────────────────────────────────────────────────
# Response handler（常に headers を返す）
# ─────────────────────────────────────────────────────────
class ResponseHandler:
    @staticmethod
    async def process_response(response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """
        返り値:
          - success:   {"status":"success","data":..., "status_code":int, "headers":dict}
          - rate_limit:{"status":"rate_limit","retry_after":float,"global":bool,"data":None,"status_code":429,"headers":dict}
          - error:     {"status":"error","data":..., "status_code":int, "headers":dict}
        """
        headers = {k: v for k, v in response.headers.items()}

        # 204 No Content
        if response.status == 204:
            return {"status": "success", "data": None, "status_code": 204, "headers": headers}

        # 429 Rate Limit
        if response.status == 429:
            retry_after = None
            is_global = False
            # ヘッダ優先
            if "Retry-After" in headers:
                try:
                    retry_after = float(headers["Retry-After"])
                except Exception:
                    retry_after = None
            # ボディも参照
            try:
                body = await response.json()
                if retry_after is None:
                    retry_after = float(body.get("retry_after", 1.0))
                is_global = bool(body.get("global", False))
            except Exception:
                pass
            if retry_after is None:
                retry_after = 1.0

            return {
                "status": "rate_limit",
                "retry_after": retry_after,
                "global": is_global,
                "data": None,
                "status_code": 429,
                "headers": headers,
            }

        # 2xx
        if 200 <= response.status < 300:
            try:
                # "application/json; charset=utf-8" も拾う
                if response.content_type and response.content_type.startswith("application/json"):
                    data = await response.json()
                else:
                    data = await response.text()
            except Exception as e:
                logger.error(f"[HTTP] read fail url={response.url} status={response.status} err={e}", exc_info=True)
                data = None

            return {"status": "success", "data": data, "status_code": response.status, "headers": headers}

        # その他エラー
        try:
            if response.content_type and response.content_type.startswith("application/json"):
                data = await response.json()
            else:
                data = await response.text()
        except Exception as e:
            logger.error(f"[HTTP] error read fail url={response.url} status={response.status} err={e}", exc_info=True)
            data = None

        return {"status": "error", "data": data, "status_code": response.status, "headers": headers}


# ─────────────────────────────────────────────────────────
# 共有HTTPクライアント（起動/終了で1つのSessionを使い回す）
# ─────────────────────────────────────────────────────────
class HTTPClient:
    _session: Optional[aiohttp.ClientSession] = None
    _bot_token: Optional[str] = None

    @classmethod
    def set_bot_token(cls, token: str) -> None:
        cls._bot_token = token

    @classmethod
    def _headers(cls) -> Dict[str, str]:
        base = {
            "User-Agent": "DiscordBot (discord.py-like, custom-queue)",
            "Content-Type": "application/json",
        }
        if cls._bot_token:
            base["Authorization"] = f"Bot {cls._bot_token}"
        return base

    @classmethod
    async def start(cls) -> None:
        if cls._session is None:
            cls._session = aiohttp.ClientSession(
                headers=cls._headers(),
                connector=aiohttp.TCPConnector(limit=100, enable_cleanup_closed=True),
                timeout=aiohttp.ClientTimeout(total=60),
            )

    @classmethod
    async def close(cls) -> None:
        if cls._session:
            await cls._session.close()
            cls._session = None

    @classmethod
    def session(cls) -> aiohttp.ClientSession:
        if cls._session is None:
            raise RuntimeError("HTTPClient not started. Call HTTPClient.start() first.")
        return cls._session

    # RLヘッダ反映（QueueManagerに委譲）
    @classmethod
    async def reflect_headers(cls, headers: Dict[str, str], bucket_id: Optional[str]) -> None:
        try:
            if bucket_id:
                bucket = discord_queue.get_or_create_bucket(bucket_id)
                # Queue側は headers: dict を受け取る想定にしておくこと
                await discord_queue.handle_response_headers(headers, bucket)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────
# 下位HTTPラッパ（Route別 / 正しいバケット設計）
# ─────────────────────────────────────────────────────────
class HTTPInteractions(HTTPClient):
    # webhook(followup) は token-major
    def _webhook_bucket(self, token: str, suffix: str) -> str:
        return f"webhook_token:{token}:{suffix}"

    # --- defer (type=5) ---
    async def respond_defer(self, interaction_id: int, token: str, *, ephemeral: bool = True):
        bucket_id = f"interaction:{interaction_id}:defer"
        url = f"{BASE_URL}/interactions/{interaction_id}/{token}/callback"
        payload: Dict[str, Any] = {"type": 5, "data": {}}
        if ephemeral:
            payload["data"]["flags"] = 64

        async def _do():
            async with self.session().post(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        # 3秒SLA対策で fastlane 優先
        if hasattr(discord_queue, "enqueue_fastlane"):
            return await discord_queue.enqueue_fastlane(_do, bucket_id=bucket_id)
        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    # --- 即時応答 (type=4) ---
    async def respond_message(self, interaction_id: int, token: str, payload: Dict[str, Any]):
        """
        payload は {"type": 4, "data": {...}} を想定
        """
        bucket_id = f"interaction:{interaction_id}:callback"
        url = f"{BASE_URL}/interactions/{interaction_id}/{token}/callback"

        async def _do():
            async with self.session().post(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        if hasattr(discord_queue, "enqueue_fastlane"):
            return await discord_queue.enqueue_fastlane(_do, bucket_id=bucket_id)
        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    # --- followup: create/edit/delete ---
    async def send_followup(self, token: str, payload: Dict[str, Any], *, priority: int = 5):
        bucket_id = self._webhook_bucket(token, "post")
        url = f"{BASE_URL}/webhooks/{APPLICATION_ID}/{token}"

        async def _do():
            async with self.session().post(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        # 初回の見える応答は fastlane 推奨
        if hasattr(discord_queue, "enqueue_fastlane"):
            return await discord_queue.enqueue_fastlane(_do, bucket_id=bucket_id)
        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    async def edit_followup(self, token: str, message_id: int, payload: Dict[str, Any], *, priority: int = 8):
        bucket_id = self._webhook_bucket(token, "patch_msg")
        url = f"{BASE_URL}/webhooks/{APPLICATION_ID}/{token}/messages/{message_id}"

        async def _do():
            async with self.session().patch(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    async def edit_original_response(self, token: str, payload: Dict[str, Any]):
        bucket_id = self._webhook_bucket(token, "patch_original")
        url = f"{BASE_URL}/webhooks/{APPLICATION_ID}/{token}/messages/@original"

        async def _do():
            async with self.session().patch(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    async def delete_followup(self, token: str, message_id: int, *, priority: int = 8):
        bucket_id = self._webhook_bucket(token, "del_msg")
        url = f"{BASE_URL}/webhooks/{APPLICATION_ID}/{token}/messages/{message_id}"

        async def _do():
            async with self.session().delete(url) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")


class HTTPMessages(HTTPClient):
    # channel-major
    def _channel_bucket(self, channel_id: int, suffix: str) -> str:
        return f"channel:{channel_id}:{suffix}"

    async def send_message(self, channel_id: int, payload: Dict[str, Any], *, priority: int = 6):
        bucket_id = self._channel_bucket(channel_id, "post")
        url = f"{BASE_URL}/channels/{channel_id}/messages"

        async def _do():
            async with self.session().post(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    async def edit_message(self, channel_id: int, message_id: int, payload: Dict[str, Any], *, priority: int = 8):
        bucket_id = self._channel_bucket(channel_id, "patch_msg")
        url = f"{BASE_URL}/channels/{channel_id}/messages/{message_id}"

        async def _do():
            async with self.session().patch(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    async def delete_message(self, channel_id: int, message_id: int, *, priority: int = 8):
        bucket_id = self._channel_bucket(channel_id, "del_msg")
        url = f"{BASE_URL}/channels/{channel_id}/messages/{message_id}"

        async def _do():
            async with self.session().delete(url) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")


class HTTPGuilds(HTTPClient):
    # guild-major
    def _guild_bucket(self, suffix: str) -> str:
        return f"guild:{MAIN_SERVER_ID}:{suffix}"

    async def create_channel(self, payload: Dict[str, Any], *, priority: int = 7):
        bucket_id = self._guild_bucket("channels_post")
        url = f"{BASE_URL}/guilds/{MAIN_SERVER_ID}/channels"

        async def _do():
            async with self.session().post(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    async def modify_member(self, user_id: int, payload: Dict[str, Any], *, priority: int = 9):
        """
        PATCH /guilds/{guild_id}/members/{user_id}
       （VC移動/ミュート/rolesフルセット など）
        """
        bucket_id = self._guild_bucket("members_patch")
        url = f"{BASE_URL}/guilds/{MAIN_SERVER_ID}/members/{user_id}"

        async def _do():
            async with self.session().patch(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")

    async def modify_roles(self, user_id: int, roles: Tuple[int, ...], *, priority: int = 9):
        """
        roles はフルセット（差分は上流で計算して渡す）
        """
        payload = {"roles": list(roles)}
        return await self.modify_member(user_id, payload, priority=priority)


class HTTPChannels(HTTPClient):
    # channel-major
    def _channel_bucket(self, channel_id: int, suffix: str) -> str:
        return f"channel:{channel_id}:{suffix}"

    async def modify_channel(self, channel_id: int, payload: Dict[str, Any], *, priority: int = 8):
        """
        name / user_limit / bitrate / permission_overwrites などの編集
        """
        bucket_id = self._channel_bucket(channel_id, "patch")
        url = f"{BASE_URL}/channels/{channel_id}"

        async def _do():
            async with self.session().patch(url, json=payload) as resp:
                out = await ResponseHandler.process_response(resp)
                await self.reflect_headers(out.get("headers", {}), bucket_id)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")


class HTTPUsers(HTTPClient):
    async def get_user(self, user_id: int, *, priority: int = 10):
        # GETは厳密なバケット管理は不要だが、統一のためenqueue
        bucket_id = f"user:get:{user_id}"
        url = f"{BASE_URL}/users/{user_id}"

        async def _do():
            async with self.session().get(url) as resp:
                out = await ResponseHandler.process_response(resp)
                # 反映不要だが無害
                await self.reflect_headers(out.get("headers", {}), bucket_id=None)
                return out

        return await discord_queue.enqueue(_do, bucket_id=bucket_id, priority="normal")


# ─────────────────────────────────────────────────────────
# 高レベル Facade（使いやすい薄ラッパ）
# ─────────────────────────────────────────────────────────
class DiscordHTTP:
    def __init__(self):
        self.interactions = HTTPInteractions()
        self.messages = HTTPMessages()
        self.guilds = HTTPGuilds()
        self.channels = HTTPChannels()
        self.users = HTTPUsers()

    # -------------------------
    # internal helpers
    # -------------------------
    @staticmethod
    def _normalize_embeds(
        embed: Optional[Any] = None,
        embeds: Optional[Sequence[Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        embed / embeds の両対応ヘルパー。
        - embed: 単体
        - embeds: シーケンス
        どちらでも / 両方でも OK。
        返り値は Discord HTTP 向けの dict(list)。
        """
        items: List[Any] = []

        if embeds is not None:
            # embeds が単体で来ても雑に対応
            if isinstance(embeds, (list, tuple)):
                items.extend(embeds)
            else:
                items.append(embeds)

        if embed is not None:
            items.append(embed)

        if not items:
            return None

        result: List[Dict[str, Any]] = []
        for e in items:
            if hasattr(e, "to_dict"):
                result.append(e.to_dict())
            else:
                # すでに dict 想定
                result.append(e)
        return result

    @staticmethod
    def _normalize_components(view: Optional[Any]) -> Optional[Any]:
        """
        view から components を生成するヘルパー。
        view=None のときは None。
        view.to_components() があればそれを使う。
        """
        if view is None:
            return None
        if hasattr(view, "to_components"):
            return view.to_components()
        # 既に components を想定してそのまま入れるケース
        return view

    # -------------------------
    # messages
    # -------------------------
    async def send_message(
        self,
        channel_id: int,
        *,
        content: Optional[str] = None,
        embed: Optional[Any] = None,
        embeds: Optional[Sequence[Any]] = None,
        view: Optional[Any] = None,
        tts: bool = False,
        allowed_mentions: Optional[Dict[str, Any]] = None,
        flags: Optional[int] = None,
        priority: int = 6,
    ):
        payload: Dict[str, Any] = {}

        if content is not None:
            payload["content"] = content

        embeds_payload = self._normalize_embeds(embed, embeds)
        if embeds_payload is not None:
            payload["embeds"] = embeds_payload

        components = self._normalize_components(view)
        if components is not None:
            payload["components"] = components

        if tts:
            payload["tts"] = True

        if allowed_mentions is not None:
            payload["allowed_mentions"] = allowed_mentions

        if flags is not None:
            payload["flags"] = flags

        return await self.messages.send_message(channel_id, payload, priority=priority)

    async def edit_message(
        self,
        channel_id: int,
        message_id: int,
        *,
        content: Optional[str] = None,
        embed: Optional[Any] = None,
        embeds: Optional[Sequence[Any]] = None,
        view: Optional[Any] = None,
        allowed_mentions: Optional[Dict[str, Any]] = None,
        flags: Optional[int] = None,
        priority: int = 8,
    ):
        payload: Dict[str, Any] = {}

        # edit の場合、「指定されたものだけ上書き」のほうが扱いやすいので
        if content is not None:
            payload["content"] = content

        embeds_payload = self._normalize_embeds(embed, embeds)
        if embeds_payload is not None:
            payload["embeds"] = embeds_payload

        components = self._normalize_components(view)
        if components is not None:
            payload["components"] = components

        if allowed_mentions is not None:
            payload["allowed_mentions"] = allowed_mentions

        if flags is not None:
            payload["flags"] = flags

        return await self.messages.edit_message(channel_id, message_id, payload, priority=priority)

    async def delete_message(
        self,
        channel_id: int,
        message_id: int,
        *,
        priority: int = 8,
    ):
        return await self.messages.delete_message(channel_id, message_id, priority=priority)

    # -------------------------
    # followups
    # -------------------------
    async def send_followup(
        self,
        token: str,
        *,
        content: Optional[str] = None,
        embed: Optional[Any] = None,
        embeds: Optional[Sequence[Any]] = None,
        view: Optional[Any] = None,
        tts: bool = False,
        allowed_mentions: Optional[Dict[str, Any]] = None,
        ephemeral: bool = False,
        flags: Optional[int] = None,
        priority: int = 5,
    ):
        payload: Dict[str, Any] = {}

        if content is not None:
            payload["content"] = content

        embeds_payload = self._normalize_embeds(embed, embeds)
        if embeds_payload is not None:
            payload["embeds"] = embeds_payload

        components = self._normalize_components(view)
        if components is not None:
            payload["components"] = components

        if tts:
            payload["tts"] = True

        if allowed_mentions is not None:
            payload["allowed_mentions"] = allowed_mentions

        # flags は明示指定 > ephemeral の順で扱う
        eff_flags = flags if flags is not None else 0
        if ephemeral:
            eff_flags |= 1 << 6  # 64
        if eff_flags:
            payload["flags"] = eff_flags

        return await self.interactions.send_followup(token, payload, priority=priority)

    async def edit_followup(
        self,
        token: str,
        message_id: int,
        *,
        content: Optional[str] = None,
        embed: Optional[Any] = None,
        embeds: Optional[Sequence[Any]] = None,
        view: Optional[Any] = None,
        allowed_mentions: Optional[Dict[str, Any]] = None,
        flags: Optional[int] = None,
        priority: int = 8,
    ):
        payload: Dict[str, Any] = {}

        if content is not None:
            payload["content"] = content

        embeds_payload = self._normalize_embeds(embed, embeds)
        if embeds_payload is not None:
            payload["embeds"] = embeds_payload

        components = self._normalize_components(view)
        if components is not None:
            payload["components"] = components

        if allowed_mentions is not None:
            payload["allowed_mentions"] = allowed_mentions

        if flags is not None:
            payload["flags"] = flags

        return await self.interactions.edit_followup(token, message_id, payload, priority=priority)

    async def delete_followup(
        self,
        token: str,
        message_id: int,
        *,
        priority: int = 8,
    ):
        return await self.interactions.delete_followup(token, message_id, priority=priority)

    # -------------------------
    # interactions (defer / type=4 / original edit)
    # -------------------------
    async def defer_interaction(
        self,
        interaction_id: int,
        token: str,
        *,
        ephemeral: bool = True,
    ):
        return await self.interactions.respond_defer(interaction_id, token, ephemeral=ephemeral)

    async def send_interaction_message(
        self,
        interaction_id: int,
        token: str,
        *,
        content: Optional[str] = None,
        embed: Optional[Any] = None,
        embeds: Optional[Sequence[Any]] = None,
        view: Optional[Any] = None,
        tts: bool = False,
        allowed_mentions: Optional[Dict[str, Any]] = None,
        ephemeral: bool = False,
        flags: Optional[int] = None,
    ):
        data: Dict[str, Any] = {}

        if content is not None:
            data["content"] = content

        embeds_payload = self._normalize_embeds(embed, embeds)
        if embeds_payload is not None:
            data["embeds"] = embeds_payload

        components = self._normalize_components(view)
        if components is not None:
            data["components"] = components

        if tts:
            data["tts"] = True

        if allowed_mentions is not None:
            data["allowed_mentions"] = allowed_mentions

        eff_flags = flags if flags is not None else 0
        if ephemeral:
            eff_flags |= 1 << 6  # 64
        if eff_flags:
            data["flags"] = eff_flags

        payload = {"type": 4, "data": data}
        return await self.interactions.respond_message(interaction_id, token, payload)

    async def edit_original_response(
        self,
        token: str,
        *,
        content: Optional[str] = None,
        embed: Optional[Any] = None,
        embeds: Optional[Sequence[Any]] = None,
        view: Optional[Any] = None,
        allowed_mentions: Optional[Dict[str, Any]] = None,
        flags: Optional[int] = None,
    ):
        payload: Dict[str, Any] = {}

        if content is not None:
            payload["content"] = content

        embeds_payload = self._normalize_embeds(embed, embeds)
        if embeds_payload is not None:
            payload["embeds"] = embeds_payload

        components = self._normalize_components(view)
        if components is not None:
            payload["components"] = components

        if allowed_mentions is not None:
            payload["allowed_mentions"] = allowed_mentions

        if flags is not None:
            payload["flags"] = flags

        return await self.interactions.edit_original_response(token, payload)

    # -------------------------
    # guild/channels
    # -------------------------
    # -------------------------
    # guild/channels
    # -------------------------
    async def create_channel(
        self,
        *,
        name: str,
        channel_type: int = 2,  # 2 = Voice
        status: Optional[str] = None,
        bitrate: Optional[int] = None,
        user_limit: Optional[int] = None,
        parent_id: Optional[int] = None,
        position: Optional[int] = None,
        priority: int = 7,
    ):
        """
        VC を中心に最低限のフィールドで作成できる create_channel。
        任意で parent_id や position も受け取れるようにしてある。
        """

        payload: Dict[str, Any] = {
            "name": name,
            "type": channel_type,
        }

        if status is not None:
            payload["status"] = status

        if bitrate is not None:
            payload["bitrate"] = bitrate

        if user_limit is not None:
            payload["user_limit"] = user_limit

        if parent_id is not None:
            payload["parent_id"] = parent_id

        if position is not None:
            payload["position"] = position

        return await self.guilds.create_channel(payload, priority=priority)

    async def edit_voice_channel(
        self,
        channel_id: int,
        *,
        name: Optional[str] = None,
        status: Optional[str] = None,
        bitrate: Optional[int] = None,
        user_limit: Optional[int] = None,
        position: Optional[int] = None,
        parent_id: Optional[int] = None,
        priority: int = 8,
    ):
        """
        VC 編集を最低限の引数で。
        指定したものだけ編集されるように None チェック。
        """

        payload: Dict[str, Any] = {}

        if name is not None:
            payload["name"] = name

        if status is not None:
            payload["status"] = status

        if bitrate is not None:
            payload["bitrate"] = bitrate

        if user_limit is not None:
            payload["user_limit"] = user_limit

        if parent_id is not None:
            payload["parent_id"] = parent_id

        if position is not None:
            payload["position"] = position

        return await self.channels.modify_channel(channel_id, payload, priority=priority)

    async def name_change(
        self,
        channel_id: int,
        new_name: str,
        *,
        priority: int = 8,
    ):
        return await self.channels.modify_channel(channel_id, {"name": new_name}, priority=priority)

    # -------------------------
    # members/roles
    # -------------------------
    async def move_member(
        self,
        user_id: int,
        target_channel_id: Optional[int],
        *,
        priority: int = 9,
    ):
        payload = {"channel_id": target_channel_id}
        return await self.guilds.modify_member(user_id, payload, priority=priority)

    async def modify_roles(
        self,
        user_id: int,
        roles: Tuple[int, ...],
        *,
        priority: int = 9,
    ):
        return await self.guilds.modify_roles(user_id, roles, priority=priority)

    # -------------------------
    # users
    # -------------------------
    async def get_user(
        self,
        user_id: int,
        *,
        priority: int = 10,
    ):
        return await self.users.get_user(user_id, priority=priority)


# ─────────────────────────────────────────────────────────
# 起動/終了ヘルパ（共有Session）
# ─────────────────────────────────────────────────────────
class HTTPLifecycle:
    @staticmethod
    async def start(bot_token: str):
        HTTPClient.set_bot_token(bot_token)
        await HTTPClient.start()

    @staticmethod
    async def close():
        await HTTPClient.close()
