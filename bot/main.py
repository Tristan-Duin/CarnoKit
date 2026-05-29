from __future__ import annotations

import logging
import sys

import discord
from discord.ext import commands

from config import cfg
from rcon.client import RconClient
from services.log_watcher import LogWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("carnokit")

EXTENSIONS = [
    "cogs.server",
    "cogs.players",
    "cogs.scheduler",
    "cogs.admin",
    "cogs.updater",
    "cogs.logs",
]


class CarnoBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.rcon = RconClient(host=cfg.rcon_host, port=cfg.rcon_port, password=cfg.rcon_password)
        self.log_watcher = LogWatcher(self)

    async def setup_hook(self) -> None:
        try:
            await self.rcon.connect()
        except Exception as exc:
            log.warning("Initial RCON connection failed (%s). Will retry on first command.", exc)
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception as exc:
                log.error("Failed to load %s: %s", ext, exc)

    async def on_ready(self) -> None:
        synced = await self.tree.sync()
        log.info("Bot online as %s — synced %d slash commands.", self.user, len(synced))

        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction, error: discord.app_commands.AppCommandError
        ):
            original = getattr(error, "original", error)
            msg = f"Command failed: {original}"
            log.warning("Slash command error: %s", original)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=cfg.server_map,
        )
        await self.change_presence(activity=activity)

    async def close(self) -> None:
        log.info("Shutting down …")
        await self.rcon.disconnect()
        await super().close()


def main() -> None:
    if not cfg.discord_token:
        log.error(
            "DISCORD_TOKEN is not set.\n"
            "Copy config.example.ini to config.ini and set your bot token."
        )
        sys.exit(1)

    bot = CarnoBot()
    bot.run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
