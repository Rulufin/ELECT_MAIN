import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv
from configs.google_setup import client
from configs.logger_setup import setup_logging

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

extensions = (
    'on_channel',
    'on_message',
    'on_reaction',
    'on_voice_state',

    'judging',
    'judging_temp',
    'list_manager',
    'profile',
    'secret_recruit',

    'points',
    'vc_create',
)

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.all(),
            help_command=None
        )

        self.timer_tasks = {}

    async def setup_hook(self):
        # Google系の初期化
        await client.initialize()

        self.clear()
        for extension in extensions:
            await self.load_extension(f"extensions.{extension}")

    # おまじない。
    async def close(self):
        await super().close()

    async def on_ready(self):
        await bot.change_presence(activity=discord.CustomActivity(name="わさびの刺激とビーフの旨み"))

        from on_event.on_ready.on_ready import on_ready_view, on_ready_recover
        await on_ready_view(bot=bot)
        await on_ready_recover(bot=bot)

        from helpers.http import HTTPClient

        HTTPClient.set_bot_token(token=BOT_TOKEN)
        await HTTPClient.start()

        retries = 3
        delay = 5  # 5秒間の遅延
        for attempt in range(retries):
            try:
                synced = await bot.tree.sync()  # 同期されたコマンドを取得
                print(f"コマンド同期成功")
                break  # 成功したらループを抜ける
            except Exception as e:
                print(f"コマンド同期失敗: {e}")
                if attempt < retries - 1:  # 最後の試行では待機しない
                    print(f"{delay}秒後に再試行します... ({attempt + 1}/{retries})")
                    await asyncio.sleep(delay)
                else:
                    print("コマンド同期を再試行できませんでした。")

bot = MyBot()
logger = setup_logging(bot)
bot.run(BOT_TOKEN)
