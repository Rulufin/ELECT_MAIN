import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from configs.google_setup import client
from configs.logger_setup import setup_logging

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

cogs_events = (
    'on_ready',
    'on_channel',
    'on_message',
    'on_reaction',
    'on_voice_state',
)

cogs_commands = (
    'judging',
    'judging_temp',
    'list_manager',
    'profile',
    'secret_recruit',
    'points',
    'vc_create',
    'rank',
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
        for cog in cogs_events:
            await self.load_extension(f"cogs.events.{cog}")
        for cog in cogs_commands:
            await self.load_extension(f"cogs.commands.{cog}")

    # おまじない。
    async def close(self):
        await super().close()


bot = MyBot()
logger = setup_logging(bot)
bot.run(BOT_TOKEN)
