from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from services.log_watcher import LogWatcher
from utils import embeds
from utils.permissions import require_mod


class LogsCog(commands.GroupCog, group_name="logs"):

    def __init__(self, bot: commands.Bot, watcher: LogWatcher):
        self.bot = bot
        self.watcher = watcher

    async def cog_load(self) -> None:
        self.watcher.start()

    async def cog_unload(self) -> None:
        self.watcher.stop()

    @app_commands.command(name="tail", description="Show the last N lines of the server log")
    @app_commands.describe(lines="Number of lines to show (default 25, max 100)")
    @require_mod
    async def tail(self, interaction: discord.Interaction, lines: int = 25):
        lines = max(1, min(lines, 100))
        entries = self.watcher.tail(lines)
        embed = embeds.log_tail(entries, title=f"Last {len(entries)} Log Lines")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="search", description="Search the log buffer for a keyword")
    @app_commands.describe(query="Search term (case-insensitive)")
    @require_mod
    async def search(self, interaction: discord.Interaction, query: str):
        results = self.watcher.search(query)
        embed = embeds.log_tail(results, title=f'Search: "{query}" ({len(results)} matches)')
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    watcher: LogWatcher = bot.log_watcher  # type: ignore[attr-defined]
    await bot.add_cog(LogsCog(bot, watcher))
