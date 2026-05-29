from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from rcon.client import RconClient
from utils import embeds
from utils.permissions import require_admin, require_mod


class PlayersCog(commands.GroupCog, group_name="players"):

    def __init__(self, bot: commands.Bot, rcon: RconClient):
        self.bot = bot
        self.rcon = rcon

    @app_commands.command(name="list", description="Show all currently online players")
    async def player_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await self.rcon.ensure_connected()
            raw = await self.rcon.command("ListPlayers")
            embed = embeds.player_list_embed(raw)
        except Exception as exc:
            embed = embeds.error("RCON Error", f"Could not reach the server.\n`{exc}`")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="kick", description="Kick a player from the server")
    @app_commands.describe(player="Player name or EOS/Steam ID", reason="Reason for kick")
    @require_admin
    async def kick(self, interaction: discord.Interaction, player: str, reason: str = ""):
        await interaction.response.defer()
        await self.rcon.ensure_connected()
        resp = await self.rcon.command(f"KickPlayer {player}")
        detail = f"Kicked **{player}**"
        if reason:
            detail += f"\nReason: {reason}"
        if resp:
            detail += f"\n\nServer response: {resp}"
        await interaction.followup.send(embed=embeds.success("Player Kicked", detail))

    @app_commands.command(name="ban", description="Ban a player from the server")
    @app_commands.describe(player="Player name or EOS/Steam ID", reason="Reason for ban")
    @require_admin
    async def ban(self, interaction: discord.Interaction, player: str, reason: str = ""):
        await interaction.response.defer()
        await self.rcon.ensure_connected()
        if reason:
            await self.rcon.command(f"ServerChat [Admin] {player} has been banned: {reason}")

        resp = await self.rcon.command(f"BanPlayer {player}")
        detail = f"Banned **{player}**"
        if reason:
            detail += f"\nReason: {reason}"
        if resp:
            detail += f"\n\nServer response: {resp}"
        await interaction.followup.send(embed=embeds.success("Player Banned", detail))

    @app_commands.command(name="unban", description="Unban a player")
    @app_commands.describe(player_id="The player's EOS or Steam ID")
    @require_admin
    async def unban(self, interaction: discord.Interaction, player_id: str):
        await interaction.response.defer()
        await self.rcon.ensure_connected()
        resp = await self.rcon.command(f"UnbanPlayer {player_id}")
        await interaction.followup.send(
            embed=embeds.success("Player Unbanned", resp or f"Unbanned `{player_id}`.")
        )

    @app_commands.command(name="message", description="Send a private in-game message to a player")
    @app_commands.describe(player="Player name or ID", text="Message to send")
    @require_mod
    async def message(self, interaction: discord.Interaction, player: str, text: str):
        await interaction.response.defer(ephemeral=True)
        await self.rcon.ensure_connected()
        resp = await self.rcon.command(f"ServerChatTo {player} {text}")
        await interaction.followup.send(
            embed=embeds.success("Message Sent", resp or f"Sent to **{player}**: {text}"),
            ephemeral=True,
        )

    @app_commands.command(name="broadcast", description="Send a server-wide broadcast message")
    @app_commands.describe(text="Message to broadcast to all players")
    @require_mod
    async def broadcast(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer()
        await self.rcon.ensure_connected()
        resp = await self.rcon.command(f"Broadcast {text}")
        await interaction.followup.send(
            embed=embeds.success("Broadcast Sent", resp or text)
        )


async def setup(bot: commands.Bot):
    rcon: RconClient = bot.rcon  # type: ignore[attr-defined]
    await bot.add_cog(PlayersCog(bot, rcon))
