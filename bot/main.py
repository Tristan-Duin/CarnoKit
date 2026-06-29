"""
ARK Survival Ascended - Cluster Management Bot

Entry point.  Run with:  python main.py

Manages a multi-map cluster: one RCON client and one log watcher per
server, all driven by the shared config.ini.
"""

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
log = logging.getLogger("ark-bot")

# Cogs to load on startup (order doesn't matter).
EXTENSIONS = [
    "cogs.cluster",
    "cogs.server",
    "cogs.players",
    "cogs.scheduler",
    "cogs.admin",
    "cogs.updater",
    "cogs.logs",
]


class ArkCommandTree(discord.app_commands.CommandTree):
    """Restrict every slash command to the single configured bot channel."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        channel_id = cfg.channel_id
        if channel_id and interaction.channel_id != channel_id:
            await interaction.response.send_message(
                f"The bot only responds in <#{channel_id}>.", ephemeral=True
            )
            return False
        return True


class ArkBot(commands.Bot):
    """The main bot class.  Holds one RCON client + log watcher per server."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents, tree_cls=ArkCommandTree)

        # One shared RCON client per server (created once, used by all cogs).
        self.rcons: dict[str, RconClient] = {
            key: RconClient(
                host=cfg.rcon_host,
                port=sc.rcon_port,
                password=cfg.admin_password,
            )
            for key, sc in cfg.servers.items()
        }

        # One log watcher per server (shared so the logs cog can read buffers).
        self.log_watchers: dict[str, LogWatcher] = {
            key: LogWatcher(self, sc) for key, sc in cfg.servers.items()
        }

    def rcon_for(self, key: str | None) -> RconClient:
        """Return the RCON client for a server key (defaults to the first)."""
        return self.rcons[cfg.server(key).key]

    async def setup_hook(self) -> None:
        # Attempt initial RCON connections (non-fatal if a server isn't up yet).
        for key, client in self.rcons.items():
            try:
                await client.connect()
            except Exception as exc:
                log.warning("Initial RCON connection to %s failed (%s).", key, exc)

        # Load all cog extensions.
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception as exc:
                log.error("Failed to load %s: %s", ext, exc)

    async def on_ready(self) -> None:
        synced = await self.tree.sync()
        log.info("Bot online as %s - synced %d slash commands.", self.user, len(synced))

        # Global error handler for slash commands.
        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction, error: discord.app_commands.AppCommandError
        ):
            # interaction_check already told the user to use the bot channel.
            if isinstance(error, discord.app_commands.CheckFailure):
                return
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

        # Set a status showing the cluster size.
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"ARK cluster - {len(cfg.servers)} maps",
        )
        await self.change_presence(activity=activity)

    async def close(self) -> None:
        log.info("Shutting down ...")
        for client in self.rcons.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        await super().close()


def main() -> None:
    if not cfg.discord_token:
        log.error(
            "DISCORD token is not set.\n"
            "Edit config.ini ([discord] token = ...) before starting the bot."
        )
        sys.exit(1)

    if not cfg.servers:
        log.error("No servers configured. Check the [servers] list in config.ini.")
        sys.exit(1)

    bot = ArkBot()
    bot.run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
