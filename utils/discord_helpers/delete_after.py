# utils/discord_helpers/delete_after.py
import discord
from discord import Message
import asyncio

async def delete_after(self, message: Message, delete_after: int = 5):
    await asyncio.sleep(delete_after)
    await message.delete()