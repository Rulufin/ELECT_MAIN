# Google_Setup.py
import gspread
import json
import os
import logging

from google.oauth2.service_account import Credentials
from google.cloud.firestore_v1 import Increment, AsyncClient
from google.api_core.exceptions import NotFound

logger = logging.getLogger(__name__)

_SCOPES = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/datastore',
]

def _load_credentials() -> Credentials:
    """環境変数 GOOGLE_CREDENTIALS_JSON から認証情報を読み込む。"""
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=_SCOPES)

    # ローカル開発用フォールバック（JSON ファイルが存在する場合のみ）
    fallback = os.path.join(os.path.dirname(__file__), '../assets/json/elect-478605-8a6fca4a90b6.json')
    if os.path.exists(fallback):
        logger.warning("GOOGLE_CREDENTIALS_JSON が未設定のため、ローカルの JSON ファイルを使用します。")
        return Credentials.from_service_account_file(fallback, scopes=_SCOPES)

    raise EnvironmentError(
        "Google 認証情報が見つかりません。"
        "環境変数 GOOGLE_CREDENTIALS_JSON にサービスアカウント JSON を設定してください。"
    )


class GoogleClient:
    def __init__(self):
        self.scope = _SCOPES
        self.creds = _load_credentials()
        self.client = gspread.authorize(self.creds)
        self.member_sheet = None
        self.voice_sheet = None
        self.firestore_db = None  # Firestore非同期クライアント

    async def initialize(self):
        try:
            await self.init_firestore()
            await self.init_channel_sheet()
        except Exception as e:
            logger.error(f"初期化中にエラーが発生しました: {e}")

    async def init_channel_sheet(self):
        pass

    async def init_firestore(self):
        # 非同期Firestoreクライアントを初期化
        self.firestore_db = AsyncClient(credentials=self.creds)
        logger.info("Firestore非同期クライアントが初期化されました")

# グローバルなclientインスタンスを用意
client = GoogleClient()
