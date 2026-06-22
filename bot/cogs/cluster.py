"""Cluster-wide overview commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from utils import embeds
from utils.formatting import parse_player_list


class ClusterCog(commands.GroupCog, group_name="cluster"):
    """Commands that operate across every server in the cluster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="status", description="Show status and player counts for every map")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = []
        for key, sc in cfg.servers.items():
            row = {
                "name": sc.name,
                "map": sc.map,
                "game_port": sc.game_port,
                "online": False,
                "players": 0,
            }
            try:
                rcon = self.bot.rcon_for(key)  # type: ignore[attr-defined]
                await rcon.ensure_connected()
                raw = await rcon.command("ListPlayers")
                row["online"] = True
                row["players"] = len(parse_player_list(raw))
            except Exception:
                row["online"] = False
            rows.append(row)
        await interaction.followup.send(embed=embeds.cluster_status(rows))


async def setup(bot: commands.Bot):
    await bot.add_cog(ClusterCog(bot))
