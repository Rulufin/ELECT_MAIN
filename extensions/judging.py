import discord
from discord.ext import commands
from discord import (
    app_commands, Interaction
)

import logging

logger = logging.getLogger(__name__)

FILENAME = "judging_extensions"

class Judging_Main_Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.commands(name="")