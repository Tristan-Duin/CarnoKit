"""Player management commands (per-map)."""

from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import server_choices
from utils import embeds
from utils.permissions import require_admin, require_mod


class PlayersCog(commands.GroupCog, group_name="players"):
    """Commands for managing players on a single map in the cluster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /players list ─────────────────────────────────────────────────────

    @app_commands.command(name="list", description="Show all currently online players")
    @app_commands.describe(server="Target map (default: first configured)")
    @app_commands.choices(server=server_choices())
    async def player_list(self, interaction: discord.Interaction, server: Optional[str] = None):
        await interaction.response.defer()
        try:
            rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
            await rcon.ensure_connected()
            raw = await rcon.command("ListPlayers")
            embed = embeds.player_list_embed(raw)
        except Exception as exc:
            embed = embeds.error("RCON Error", f"Could not reach the server.\n`{exc}`")
        await interaction.followup.send(embed=embed)

    # ── /players kick ─────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Kick a player from the server")
    @app_commands.describe(player="Player name or EOS/Steam ID", server="Target map (default: first)", reason="Reason for kick")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def kick(self, interaction: discord.Interaction, player: str, server: Optional[str] = None, reason: str = ""):
        await interaction.response.defer()
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        resp = await rcon.command(f"KickPlayer {player}")
        detail = f"Kicked **{player}**"
        if reason:
            detail += f"\nReason: {reason}"
        if resp:
            detail += f"\n\nServer response: {resp}"
        await interaction.followup.send(embed=embeds.success("Player Kicked", detail))

    # ── /players ban ──────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Ban a player from the server")
    @app_commands.describe(player="Player name or EOS/Steam ID", server="Target map (default: first)", reason="Reason for ban")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def ban(self, interaction: discord.Interaction, player: str, server: Optional[str] = None, reason: str = ""):
        await interaction.response.defer()
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()

        # Notify the player before banning if a reason is given.
        if reason:
            await rcon.command(f"ServerChat [Admin] {player} has been banned: {reason}")

        resp = await rcon.command(f"BanPlayer {player}")
        detail = f"Banned **{player}**"
        if reason:
            detail += f"\nReason: {reason}"
        if resp:
            detail += f"\n\nServer response: {resp}"
        await interaction.followup.send(embed=embeds.success("Player Banned", detail))

    # ── /players unban ────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Unban a player")
    @app_commands.describe(player_id="The player's EOS or Steam ID", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def unban(self, interaction: discord.Interaction, player_id: str, server: Optional[str] = None):
        await interaction.response.defer()
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        resp = await rcon.command(f"UnbanPlayer {player_id}")
        await interaction.followup.send(
            embed=embeds.success("Player Unbanned", resp or f"Unbanned `{player_id}`.")
        )

    # ── /players message ──────────────────────────────────────────────────

    @app_commands.command(name="message", description="Send a private in-game message to a player")
    @app_commands.describe(player="Player name or ID", text="Message to send", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_mod
    async def message(self, interaction: discord.Interaction, player: str, text: str, server: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        resp = await rcon.command(f"ServerChatTo {player} {text}")
        await interaction.followup.send(
            embed=embeds.success("Message Sent", resp or f"Sent to **{player}**: {text}"),
            ephemeral=True,
        )

    # ── /players broadcast ────────────────────────────────────────────────

    @app_commands.command(name="broadcast", description="Send a server-wide broadcast message")
    @app_commands.describe(text="Message to broadcast to all players", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_mod
    async def broadcast(self, interaction: discord.Interaction, text: str, server: Optional[str] = None):
        await interaction.response.defer()
        rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
        await rcon.ensure_connected()
        resp = await rcon.command(f'ServerChat "{text}"')
        await interaction.followup.send(
            embed=embeds.success("Broadcast Sent", resp or text)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayersCog(bot))
