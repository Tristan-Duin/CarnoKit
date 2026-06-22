"""Admin / cheat commands routed through RCON (per-map)."""

from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import server_choices
from utils import embeds
from utils.permissions import require_admin, require_owner


class AdminCog(commands.GroupCog, group_name="admin"):
    """Powerful admin commands - item spawning, teleportation, etc."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _exec(self, interaction: discord.Interaction, server: Optional[str], cmd: str, label: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            rcon = self.bot.rcon_for(server)  # type: ignore[attr-defined]
            await rcon.ensure_connected()
            resp = await rcon.command(cmd)
            await interaction.followup.send(
                embed=embeds.success(label, resp or f"`{cmd}` executed."),
                ephemeral=True,
            )
        except Exception as exc:
            await interaction.followup.send(
                embed=embeds.error("RCON Error", f"Server unreachable.\n`{exc}`"),
                ephemeral=True,
            )

    # ── /admin give ───────────────────────────────────────────────────────

    @app_commands.command(name="give", description="Give an item to a player")
    @app_commands.describe(
        player="Player EOS/Steam ID",
        item="Item blueprint path",
        quantity="Number of items (default 1)",
        quality="Item quality 0-100 (default 0)",
        server="Target map (default: first)",
    )
    @app_commands.choices(server=server_choices())
    @require_admin
    async def give(
        self,
        interaction: discord.Interaction,
        player: str,
        item: str,
        quantity: int = 1,
        quality: int = 0,
        server: Optional[str] = None,
    ):
        cmd = f'cheat GiveItemToPlayer {player} "{item}" {quantity} {quality} false'
        await self._exec(interaction, server, cmd, f"Gave {quantity}x item to {player}")

    # ── /admin xp ─────────────────────────────────────────────────────────

    @app_commands.command(name="xp", description="Give experience points to a player")
    @app_commands.describe(player="Player EOS/Steam ID", amount="Amount of XP", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def xp(self, interaction: discord.Interaction, player: str, amount: int, server: Optional[str] = None):
        cmd = f"cheat GiveExpToPlayer {player} {amount} false false"
        await self._exec(interaction, server, cmd, f"Gave {amount:,} XP to {player}")

    # ── /admin teleport ───────────────────────────────────────────────────

    @app_commands.command(name="teleport", description="Teleport a player to you (must be in-game as admin)")
    @app_commands.describe(player="Player name or ID", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def teleport(self, interaction: discord.Interaction, player: str, server: Optional[str] = None):
        cmd = f"cheat TeleportPlayerNameToMe {player}"
        await self._exec(interaction, server, cmd, f"Teleported {player}")

    # ── /admin summon ─────────────────────────────────────────────────────

    @app_commands.command(name="summon", description="Spawn a creature at a random player")
    @app_commands.describe(creature="Creature blueprint path or class name", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def summon(self, interaction: discord.Interaction, creature: str, server: Optional[str] = None):
        cmd = f"cheat Summon {creature}"
        await self._exec(interaction, server, cmd, f"Summoned {creature}")

    # ── /admin destroy-tame ───────────────────────────────────────────────

    @app_commands.command(name="destroy-tame", description="Destroy a specific tamed dino by looking at it (in-game)")
    @app_commands.describe(server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_owner
    async def destroy_tame(self, interaction: discord.Interaction, server: Optional[str] = None):
        await self._exec(interaction, server, "cheat DestroyMyTarget", "Destroy Target Sent")

    # ── /admin kill ───────────────────────────────────────────────────────

    @app_commands.command(name="kill", description="Kill a player by their ID")
    @app_commands.describe(player="Player EOS/Steam ID", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_owner
    async def kill(self, interaction: discord.Interaction, player: str, server: Optional[str] = None):
        cmd = f"cheat KillPlayer {player}"
        await self._exec(interaction, server, cmd, f"Killed player {player}")

    # ── /admin clear-inventory ────────────────────────────────────────────

    @app_commands.command(name="clear-inventory", description="Clear a player's inventory")
    @app_commands.describe(player="Player EOS/Steam ID", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_owner
    async def clear_inventory(self, interaction: discord.Interaction, player: str, server: Optional[str] = None):
        cmd = f"cheat ClearPlayerInventory {player} true true true"
        await self._exec(interaction, server, cmd, f"Cleared inventory for {player}")

    # ── /admin set-level ──────────────────────────────────────────────────

    @app_commands.command(name="set-level", description="Set a player's level")
    @app_commands.describe(player="Player EOS/Steam ID", level="Target level", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def set_level(self, interaction: discord.Interaction, player: str, level: int, server: Optional[str] = None):
        cmd = f"cheat SetPlayerLevel {player} {level}"
        await self._exec(interaction, server, cmd, f"Set {player} to level {level}")

    # ── /admin rename-tribe ───────────────────────────────────────────────

    @app_commands.command(name="rename-tribe", description="Rename a tribe")
    @app_commands.describe(tribe_name="Current tribe name", new_name="New tribe name", server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def rename_tribe(self, interaction: discord.Interaction, tribe_name: str, new_name: str, server: Optional[str] = None):
        cmd = f'cheat RenameTribe "{tribe_name}" "{new_name}"'
        await self._exec(interaction, server, cmd, f"Renamed tribe '{tribe_name}' -> '{new_name}'")

    # ── /admin pvp-toggle ─────────────────────────────────────────────────

    @app_commands.command(name="pvp-toggle", description="Toggle global PvP damage (white flag)")
    @app_commands.describe(server="Target map (default: first)")
    @app_commands.choices(server=server_choices())
    @require_owner
    async def pvp_toggle(self, interaction: discord.Interaction, server: Optional[str] = None):
        await self._exec(interaction, server, "cheat EnablePvP", "PvP Toggle Sent")


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
