"""Log viewing commands backed by the per-server LogWatcher services."""

from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg, server_choices
from utils import embeds
from utils.permissions import require_admin


class LogsCog(commands.GroupCog, group_name="logs"):
    """Commands for viewing and searching ARK server logs (per-map)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        for watcher in self.bot.log_watchers.values():  # type: ignore[attr-defined]
            watcher.start()

    async def cog_unload(self) -> None:
        for watcher in self.bot.log_watchers.values():  # type: ignore[attr-defined]
            watcher.stop()

    def _watcher(self, server: Optional[str]):
        key = cfg.server(server).key
        return self.bot.log_watchers[key]  # type: ignore[attr-defined]

    # ── /logs tail ────────────────────────────────────────────────────────

    @app_commands.command(name="tail", description="Show the last N lines of a server log")
    @app_commands.describe(lines="Number of lines to show (default 25, max 100)", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def tail(self, interaction: discord.Interaction, lines: int = 25, server: Optional[str] = None):
        lines = max(1, min(lines, 100))
        sc = cfg.server(server)
        entries = self._watcher(server).tail(lines)
        embed = embeds.log_tail(entries, title=f"Last {len(entries)} Log Lines - {sc.name}")
        await interaction.response.send_message(embed=embed)

    # ── /logs search ──────────────────────────────────────────────────────

    @app_commands.command(name="search", description="Search a server's log buffer for a keyword")
    @app_commands.describe(query="Search term (case-insensitive)", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def search(self, interaction: discord.Interaction, query: str, server: Optional[str] = None):
        sc = cfg.server(server)
        results = self._watcher(server).search(query)
        embed = embeds.log_tail(results, title=f'Search "{query}" on {sc.name} ({len(results)} matches)')
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LogsCog(bot))
