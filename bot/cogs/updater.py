"""Auto-update cog - detect new ARK builds and orchestrate the cluster update."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from services.update_checker import UpdateChecker
from utils import embeds
from utils.permissions import require_admin, require_owner


class ConfirmUpdateView(discord.ui.View):
    """Confirmation prompt for a forced update."""

    def __init__(self, *, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.confirmed: bool | None = None

    @discord.ui.button(label="Start Update", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class UpdaterCog(commands.GroupCog, group_name="update"):
    """Commands for checking and applying ARK server/mod updates across the cluster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.checker = UpdateChecker(bot)

    async def cog_load(self) -> None:
        self.checker.start()

    async def cog_unload(self) -> None:
        self.checker.stop()

    # ── /update check ─────────────────────────────────────────────────────

    @app_commands.command(name="check", description="Check if a server or mod refresh is needed")
    @require_admin
    async def check(self, interaction: discord.Interaction):
        await interaction.response.defer()
        current, latest = await self.checker.check_now()

        if self.checker.has_update():
            embed = embeds.update_available(
                current,
                latest or "unknown",
                configured_mods=cfg.mods_list,
                missing_mods=self.checker.missing_mods,
            )
        else:
            embed = embeds.success(
                "Up to Date",
                (
                    f"Installed build `{current}` is the latest available, "
                    f"and configured mods `{','.join(cfg.mods_list) or 'none'}` "
                    "were found on disk."
                ),
            )
        await interaction.followup.send(embed=embed)

    # ── /update status ────────────────────────────────────────────────────

    @app_commands.command(name="status", description="Show game build and configured mod update info")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if not self.checker.current_build:
            await self.checker.check_now()
        embed = embeds.update_status(
            current_build=self.checker.current_build or "unknown",
            latest_build=self.checker.latest_build,
            auto_update=True,
            check_interval=cfg.update_check_minutes,
            configured_mods=cfg.mods_list,
            missing_mods=self.checker.missing_mods,
        )
        await interaction.followup.send(embed=embed)

    # ── /update now ───────────────────────────────────────────────────────

    @app_commands.command(name="now", description="Force an immediate game/mod refresh with countdown")
    @require_owner
    async def now(self, interaction: discord.Interaction):
        view = ConfirmUpdateView()
        await interaction.response.send_message(
            embed=embeds.warning(
                "Force Cluster Game/Mod Refresh",
                (
                    f"This will start a **{cfg.update_countdown_minutes}-minute** countdown, "
                    f"then save, restart, and refresh the game server plus configured mods "
                    f"on **every map** in the cluster.\n\n"
                    f"Continue?"
                ),
            ),
            view=view,
        )
        await view.wait()

        if view.confirmed:
            await interaction.edit_original_response(
                embed=embeds.info(
                    "Game/Mod Refresh Started",
                    f"Countdown has begun ({cfg.update_countdown_minutes} min). "
                    f"Players will be warned in-game on every map.",
                ),
                view=None,
            )
            await self.checker.run_update_cycle()
        else:
            await interaction.edit_original_response(
                embed=embeds.info("Cancelled", "Update was cancelled."),
                view=None,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(UpdaterCog(bot))
