from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from rcon.client import RconClient
from utils import embeds
from utils.permissions import require_admin, require_owner


class AdminCog(commands.GroupCog, group_name="admin"):
    """Powerful admin commands"""

    def __init__(self, bot: commands.Bot, rcon: RconClient):
        self.bot = bot
        self.rcon = rcon

    async def _exec(self, interaction: discord.Interaction, cmd: str, label: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            await self.rcon.ensure_connected()
            resp = await self.rcon.command(cmd)
            await interaction.followup.send(
                embed=embeds.success(label, resp or f"`{cmd}` executed."),
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(
                embed=embeds.error("RCON Error", f"Server unreachable.\n`{exc}`"),
                ephemeral=True,
            )

    @app_commands.command(name="give", description="Give an item to a player")
    @app_commands.describe(
        player="Player EOS/Steam ID",
        item="Item blueprint path",
        quantity="Number of items (default 1)",
        quality="Item quality 0-100 (default 0)",
    )
    @require_admin
    async def give(
        self,
        interaction: discord.Interaction,
        player: str,
        item: str,
        quantity: int = 1,
        quality: int = 0,
    ):
        cmd = f'cheat GiveItemToPlayer {player} "{item}" {quantity} {quality} false'
        await self._exec(interaction, cmd, f"Gave {quantity}× item to {player}")

    @app_commands.command(name="xp", description="Give experience points to a player")
    @app_commands.describe(player="Player EOS/Steam ID", amount="Amount of XP")
    @require_admin
    async def xp(self, interaction: discord.Interaction, player: str, amount: int):
        cmd = f"cheat GiveExpToPlayer {player} {amount} false false"
        await self._exec(interaction, cmd, f"Gave {amount:,} XP to {player}")

    @app_commands.command(name="teleport", description="Teleport a player to you (must be in-game as admin)")
    @app_commands.describe(player="Player name or ID")
    @require_admin
    async def teleport(self, interaction: discord.Interaction, player: str):
        cmd = f"cheat TeleportPlayerNameToMe {player}"
        await self._exec(interaction, cmd, f"Teleported {player}")

    @app_commands.command(name="summon", description="Spawn a creature at a random player")
    @app_commands.describe(creature="Creature blueprint path or class name")
    @require_admin
    async def summon(self, interaction: discord.Interaction, creature: str):
        cmd = f"cheat Summon {creature}"
        await self._exec(interaction, cmd, f"Summoned {creature}")

    @app_commands.command(name="destroy-tame", description="Destroy a specific tamed dino by looking at it (in-game)")
    @require_owner
    async def destroy_tame(self, interaction: discord.Interaction):
        await self._exec(interaction, "cheat DestroyMyTarget", "Destroy Target Sent")

    @app_commands.command(name="kill", description="Kill a player by their ID")
    @app_commands.describe(player="Player EOS/Steam ID")
    @require_owner
    async def kill(self, interaction: discord.Interaction, player: str):
        cmd = f"cheat KillPlayer {player}"
        await self._exec(interaction, cmd, f"Killed player {player}")

    @app_commands.command(name="clear-inventory", description="Clear a player's inventory")
    @app_commands.describe(player="Player EOS/Steam ID")
    @require_owner
    async def clear_inventory(self, interaction: discord.Interaction, player: str):
        cmd = f"cheat ClearPlayerInventory {player} true true true"
        await self._exec(interaction, cmd, f"Cleared inventory for {player}")

    @app_commands.command(name="set-level", description="Set a player's level")
    @app_commands.describe(player="Player EOS/Steam ID", level="Target level")
    @require_admin
    async def set_level(self, interaction: discord.Interaction, player: str, level: int):
        cmd = f"cheat SetPlayerLevel {player} {level}"
        await self._exec(interaction, cmd, f"Set {player} to level {level}")

    @app_commands.command(name="rename-tribe", description="Rename a tribe")
    @app_commands.describe(tribe_name="Current tribe name", new_name="New tribe name")
    @require_admin
    async def rename_tribe(self, interaction: discord.Interaction, tribe_name: str, new_name: str):
        cmd = f'cheat RenameTribe "{tribe_name}" "{new_name}"'
        await self._exec(interaction, cmd, f"Renamed tribe '{tribe_name}' → '{new_name}'")

    @app_commands.command(name="pvp-toggle", description="Toggle global PvP damage (white flag)")
    @require_owner
    async def pvp_toggle(self, interaction: discord.Interaction):
        await self._exec(interaction, "cheat EnablePvP", "PvP Toggle Sent")


async def setup(bot: commands.Bot):
    rcon: RconClient = bot.rcon  # type: ignore[attr-defined]
    await bot.add_cog(AdminCog(bot, rcon))
