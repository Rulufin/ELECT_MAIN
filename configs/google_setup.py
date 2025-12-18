# Google_Setup.py
import gspread
from google.oauth2.service_account import Credentials
from google.cloud.firestore_v1 import Increment, AsyncClient
from google.api_core.exceptions import NotFound  # 修正箇所
import logging
import os

logger = logging.getLogger(__name__)

class GoogleClient:
    def __init__(self):
        self.scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/datastore'  # Firestore 用スコープを追加
        ]
        self.json_file_path = os.path.join(os.path.dirname(__file__), '../assets/json/elect-478605-8a6fca4a90b6.json')
        self.creds = Credentials.from_service_account_file(self.json_file_path, scopes=self.scope)
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
