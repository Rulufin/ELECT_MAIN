import logging
from logging.handlers import RotatingFileHandler
import discord
from discord.ext import commands
import time

# ログサーバー
LOG_GUILD_ID = 1421436016442740749
LOG_CHANNEL_ID = 1443850229949661194

class DiscordLogHandler(logging.Handler):
    RATE_LIMIT_THRESHOLD = 300  # 5分 (300秒)

    def __init__(self, bot: commands.Bot, guild_id, channel_id):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.last_sent_per_message = {}  # メッセージごとの最終送信時刻

    def emit(self, record):
        if not self.filter(record):
            return  # フィルタリングされたログは処理しない
        
        log_entry = self.format(record)
        guild = self.bot.get_guild(self.guild_id)

        if guild:
            channel = guild.get_channel(self.channel_id)
            if channel:
                current_time = time.time()

                # 直近で同じログが送信されたかチェック
                last_sent_time = self.last_sent_per_message.get(log_entry, 0)
                
                if current_time - last_sent_time >= self.RATE_LIMIT_THRESHOLD:
                    self.last_sent_per_message[log_entry] = current_time  # 送信時間を更新
                    self.bot.loop.create_task(self.send_log(channel, log_entry))

    async def send_log(self, channel, log_entry):
        try:
            await channel.send(f"<@1106998270468829295>\n```{log_entry}```")
        except discord.DiscordException as e:
            print(f"Failed to send log to Discord: {e}")

        # メモリ節約のため、古いログエントリを削除（オプション）
        now = time.time()
        self.last_sent_per_message = {msg: ts for msg, ts in self.last_sent_per_message.items() if now - ts < 3600}

class WebSocketFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # メッセージ部分をチェック
        if "WebSocket" in record.getMessage():
            return False

        # メッセージテンプレートをチェック
        if "WebSocket" in str(record.msg):
            return False

        # 引数をチェック
        if record.args and any("WebSocket" in str(arg) for arg in record.args):
            return False

        # 例外情報をチェック
        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            if "WebSocket" in exc_type.__name__:
                return False
            if "WebSocket" in str(exc_value):
                return False

        # 例外テキストをチェック
        if record.exc_text and "WebSocket" in record.exc_text:
            return False

        return True

def setup_logging(bot: commands.Bot):
    # ルートロガーの設定
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # 全体のレベルはDEBUGに設定してもOK（個別にハンドラで制御）

    log_format = (
        "日時: %(asctime)s\n"
        "ファイル名: %(filename)s\n"
        "関数名: %(funcName)s\n"
        "ログレベル: %(levelname)s\n"
        "行番号: %(lineno)d\n"
        "メッセージ: %(message)s\n"
        "-------------------------------"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(log_format)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)  # コンソール用のログレベルを設定
    logger.addHandler(console_handler)

    # File handler (必要に応じて使用)
    file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(console_formatter)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(WebSocketFilter())  # フィルタを追加
    logger.addHandler(file_handler)

    # Discord handler
    discord_handler = DiscordLogHandler(bot, LOG_GUILD_ID, LOG_CHANNEL_ID)
    discord_formatter = logging.Formatter(log_format)
    discord_handler.setFormatter(discord_formatter)
    discord_handler.setLevel(logging.ERROR)  # Discord用のログレベルを設定
    discord_handler.addFilter(WebSocketFilter())  # フィルタを追加
    logger.addHandler(discord_handler)

    return logger
