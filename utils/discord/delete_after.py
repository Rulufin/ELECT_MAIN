import discord
from discord import Message
import asyncio

async def delete_after(message: Message, delete_after: int = 5):
    await asyncio.sleep(delete_after)
    await message.delete()