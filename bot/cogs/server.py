from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from rcon.client import RconClient
from utils import embeds
from utils.permissions import require_admin, require_owner


class ConfirmView(discord.ui.View):

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

    def __init__(self, bot: commands.Bot, rcon: RconClient):
        self.bot = bot
        self.rcon = rcon

    @app_commands.command(name="status", description="Show current server status and online players")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await self.rcon.ensure_connected()
            raw_players = await self.rcon.command("ListPlayers")
            from utils.formatting import parse_player_list
            players = parse_player_list(raw_players)
            embed = embeds.server_status(
                online=True,
                player_count=len(players),
                player_list=raw_players,
                map_name=cfg.server_map,
                rcon_host=cfg.rcon_host,
                rcon_port=cfg.rcon_port,
            )
        except Exception:
            embed = embeds.server_status(
                online=False,
                player_count=0,
                player_list="",
                map_name=cfg.server_map,
                rcon_host=cfg.rcon_host,
                rcon_port=cfg.rcon_port,
            )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="save", description="Force the server to save the world")
    @require_admin
    async def save(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await self.rcon.ensure_connected()
            resp = await self.rcon.command("SaveWorld")
            await interaction.followup.send(embed=embeds.success("World Saved", resp or "SaveWorld executed."))
        except Exception as exc:
            await interaction.followup.send(embed=embeds.error("RCON Error", f"`{exc}`"))

    @app_commands.command(name="destroy-wild-dinos", description="Destroy all wild dinos (requires confirmation)")
    @require_admin
    async def destroy_wild_dinos(self, interaction: discord.Interaction):
        view = ConfirmView()
        await interaction.response.send_message(
            embed=embeds.warning(
                "Destroy Wild Dinos",
                "This will **destroy all wild dinos** on the map. They will respawn gradually.\n\nAre you sure?",
            ),
            view=view,
        )
        await view.wait()
        if view.confirmed:
            await self.rcon.ensure_connected()
            resp = await self.rcon.command("DestroyWildDinos")
            await interaction.edit_original_response(
                embed=embeds.success("Wild Dinos Destroyed", resp or "DestroyWildDinos executed."),
                view=None,
            )
        else:
            await interaction.edit_original_response(
                embed=embeds.info("Cancelled", "Destroy wild dinos was cancelled."),
                view=None,
            )

    @app_commands.command(name="motd", description="Get or set the Message of the Day")
    @app_commands.describe(message="New MOTD text (omit to show current)")
    @require_admin
    async def motd(self, interaction: discord.Interaction, message: str | None = None):
        await interaction.response.defer()
        await self.rcon.ensure_connected()
        if message:
            resp = await self.rcon.command(f"SetMessageOfTheDay {message}")
            await interaction.followup.send(embed=embeds.success("MOTD Updated", resp or f"MOTD set to: {message}"))
        else:
            resp = await self.rcon.command("ShowMessageOfTheDay")
            await interaction.followup.send(embed=embeds.info("Message of the Day", resp or "(no MOTD set)"))

    @app_commands.command(name="time", description="Set the in-game time of day")
    @app_commands.describe(time="Time in HH:MM format (e.g. 12:00)")
    @require_admin
    async def set_time(self, interaction: discord.Interaction, time: str):
        await interaction.response.defer()
        await self.rcon.ensure_connected()
        resp = await self.rcon.command(f"SetTimeOfDay {time}")
        await interaction.followup.send(embed=embeds.success("Time Set", resp or f"Time set to {time}."))

    @app_commands.command(name="raw", description="Execute a raw RCON command (owner only)")
    @app_commands.describe(command="The RCON command to execute")
    @require_owner
    async def raw(self, interaction: discord.Interaction, command: str):
        await interaction.response.defer(ephemeral=True)
        await self.rcon.ensure_connected()
        resp = await self.rcon.command(command)
        await interaction.followup.send(embed=embeds.rcon_response(command, resp), ephemeral=True)


async def setup(bot: commands.Bot):
    rcon: RconClient = bot.rcon  # type: ignore[attr-defined]
    await bot.add_cog(ServerCog(bot, rcon))
