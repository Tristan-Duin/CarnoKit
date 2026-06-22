"""Server management commands (per-map)."""

from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg, server_choices
from utils import embeds
from utils.formatting import parse_player_list
from utils.permissions import require_admin, require_owner


class ConfirmView(discord.ui.View):
    """Yes/No confirmation prompt."""

    def __init__(self, *, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.confirmed: bool | None = None

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class ServerCog(commands.GroupCog, group_name="server"):
    """Commands for monitoring and managing a single map in the cluster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /server status ────────────────────────────────────────────────────

    @app_commands.command(name="status", description="Show a server's status and online players")
    @app_commands.describe(server="Target map (default: first configured)")
    @app_commands.choices(server=server_choices())
    async def status(self, interaction: discord.Interaction, server: Optional[str] = None):
        await interaction.response.defer()
        sc = cfg.server(server)
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        try:
            await rcon.ensure_connected()
            raw_players = await rcon.command("ListPlayers")
            players = parse_player_list(raw_players)
            embed = embeds.server_status(
                online=True,
                player_count=len(players),
                player_list=raw_players,
                map_name=sc.map,
                rcon_host=cfg.rcon_host,
                rcon_port=sc.rcon_port,
                server_name=sc.name,
            )
        except Exception:
            embed = embeds.server_status(
                online=False,
                player_count=0,
                player_list="",
                map_name=sc.map,
                rcon_host=cfg.rcon_host,
                rcon_port=sc.rcon_port,
                server_name=sc.name,
            )
        await interaction.followup.send(embed=embed)

    # ── /server save ──────────────────────────────────────────────────────

    @app_commands.command(name="save", description="Force a server to save the world")
    @app_commands.describe(server="Target map (default: first configured)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def save(self, interaction: discord.Interaction, server: Optional[str] = None):
        await interaction.response.defer()
        sc = cfg.server(server)
        try:
            rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
            await rcon.ensure_connected()
            resp = await rcon.command("SaveWorld")
            await interaction.followup.send(
                embed=embeds.success(f"World Saved - {sc.name}", resp or "SaveWorld executed.")
            )
        except Exception as exc:
            await interaction.followup.send(embed=embeds.error("RCON Error", f"`{exc}`"))

    # ── /server destroy-wild-dinos ────────────────────────────────────────

    @app_commands.command(name="destroy-wild-dinos", description="Destroy all wild dinos on a map (requires confirmation)")
    @app_commands.describe(server="Target map (default: first configured)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def destroy_wild_dinos(self, interaction: discord.Interaction, server: Optional[str] = None):
        sc = cfg.server(server)
        view = ConfirmView()
        await interaction.response.send_message(
            embed=embeds.warning(
                f"Destroy Wild Dinos - {sc.name}",
                "This will **destroy all wild dinos** on the map. They will respawn gradually.\n\nAre you sure?",
            ),
            view=view,
        )
        await view.wait()
        if view.confirmed:
            rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
            await rcon.ensure_connected()
            resp = await rcon.command("DestroyWildDinos")
            await interaction.edit_original_response(
                embed=embeds.success("Wild Dinos Destroyed", resp or "DestroyWildDinos executed."),
                view=None,
            )
        else:
            await interaction.edit_original_response(
                embed=embeds.info("Cancelled", "Destroy wild dinos was cancelled."),
                view=None,
            )

    # ── /server motd ──────────────────────────────────────────────────────

    @app_commands.command(name="motd", description="Get or set the Message of the Day")
    @app_commands.describe(server="Target map (default: first configured)", message="New MOTD text (omit to show current)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def motd(self, interaction: discord.Interaction, server: Optional[str] = None, message: str | None = None):
        await interaction.response.defer()
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        if message:
            resp = await rcon.command(f"SetMessageOfTheDay {message}")
            await interaction.followup.send(embed=embeds.success("MOTD Updated", resp or f"MOTD set to: {message}"))
        else:
            resp = await rcon.command("ShowMessageOfTheDay")
            await interaction.followup.send(embed=embeds.info("Message of the Day", resp or "(no MOTD set)"))

    # ── /server time ──────────────────────────────────────────────────────

    @app_commands.command(name="time", description="Set the in-game time of day")
    @app_commands.describe(server="Target map (default: first configured)", time="Time in HH:MM format (e.g. 12:00)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def set_time(self, interaction: discord.Interaction, time: str, server: Optional[str] = None):
        await interaction.response.defer()
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        resp = await rcon.command(f"SetTimeOfDay {time}")
        await interaction.followup.send(embed=embeds.success("Time Set", resp or f"Time set to {time}."))

    # ── /server raw ───────────────────────────────────────────────────────

    @app_commands.command(name="raw", description="Execute a raw RCON command (owner only)")
    @app_commands.describe(server="Target map (default: first configured)", command="The RCON command to execute")
    @app_commands.choices(server=server_choices())
    @require_owner
    async def raw(self, interaction: discord.Interaction, command: str, server: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        resp = await rcon.command(command)
        await interaction.followup.send(embed=embeds.rcon_response(command, resp), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCog(bot))
