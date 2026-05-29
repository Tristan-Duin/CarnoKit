from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import cfg
from rcon.client import RconClient
from services.update_checker import UpdateChecker
from utils import embeds
from utils.permissions import require_admin, require_owner


class ConfirmUpdateView(discord.ui.View):

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

    def __init__(self, bot: commands.Bot, rcon: RconClient):
        self.bot = bot
        self.rcon = rcon
        self.checker = UpdateChecker(rcon, bot)

    async def cog_load(self) -> None:
        self.checker.start()

    async def cog_unload(self) -> None:
        self.checker.stop()

    @app_commands.command(name="check", description="Check if a server update is available")
    @require_admin
    async def check(self, interaction: discord.Interaction):
        await interaction.response.defer()
        current, latest = await self.checker.check_now()

        if self.checker.has_update():
            embed = embeds.update_available(current, latest or "unknown")
        else:
            embed = embeds.success(
                "Up to Date",
                f"Installed build `{current}` is the latest available.",
            )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="status", description="Show current and latest build info")
    async def status(self, interaction: discord.Interaction):
        embed = embeds.update_status(
            current_build=self.checker.current_build or "unknown",
            latest_build=self.checker.latest_build,
            auto_update=True,
            check_interval=cfg.update_check_minutes,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="now", description="Force an immediate update cycle with countdown")
    @require_owner
    async def now(self, interaction: discord.Interaction):
        view = ConfirmUpdateView()
        await interaction.response.send_message(
            embed=embeds.warning(
                "Force Update",
                (
                    f"This will start a **{cfg.update_countdown_minutes}-minute** countdown, "
                    f"then save, shut down, update via SteamCMD, and restart the server.\n\n"
                    f"Continue?"
                ),
            ),
            view=view,
        )
        await view.wait()

        if view.confirmed:
            await interaction.edit_original_response(
                embed=embeds.info(
                    "Update Started",
                    f"Countdown has begun ({cfg.update_countdown_minutes} min). "
                    f"Players will be warned in-game.",
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
    rcon: RconClient = bot.rcon  # type: ignore[attr-defined]
    await bot.add_cog(UpdaterCog(bot, rcon))
