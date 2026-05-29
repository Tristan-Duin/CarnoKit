from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Coroutine, Optional

import discord

from config import cfg
from utils import embeds
from utils.formatting import countdown_label

if TYPE_CHECKING:
    from rcon.client import RconClient

log = logging.getLogger(__name__)

ASA_APP_ID = "2430930"  # Dedicated server Steam app ID

# Standard countdown warning schedule (seconds before shutdown).
_WARN_SCHEDULE = [1800, 900, 300, 60, 30]


class UpdateChecker:

    def __init__(
        self,
        rcon: RconClient,
        bot: discord.Client,
        *,
        on_shutdown: Optional[Callable[[], Coroutine]] = None,
    ):
        self.rcon = rcon
        self.bot = bot
        self._on_shutdown = on_shutdown  # callback to stop the server process
        self._task: Optional[asyncio.Task] = None
        self._updating = False
        self.current_build: str = ""
        self.latest_build: Optional[str] = None
        self._enabled = True

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._check_loop())
        log.info("Update checker started (every %d min).", cfg.update_check_minutes)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def check_now(self) -> tuple[str, str | None]:
        """Check for updates right now.  Returns (current, latest)."""
        self.current_build = await asyncio.to_thread(self._read_installed_build)
        self.latest_build = await asyncio.to_thread(self._fetch_latest_build)
        return self.current_build, self.latest_build

    def has_update(self) -> bool:
        return bool(
            self.current_build
            and self.latest_build
            and self.current_build != self.latest_build
        )

    async def run_update_cycle(self, countdown_seconds: int | None = None) -> None:
        """Execute the full update cycle: countdown → save → stop → update → restart."""
        if self._updating:
            log.warning("Update cycle already in progress.")
            return

        self._updating = True
        try:
            countdown = countdown_seconds or (cfg.update_countdown_minutes * 60)
            await self._countdown(countdown, reason="update")
            await self._save_and_stop()
            await self._run_steamcmd_update()
            await self._start_server()
            await self._post_alert(embeds.success(
                "Server Updated & Restarted",
                f"Build `{self.latest_build}` is now live.",
            ))
        except Exception as exc:
            log.error("Update cycle failed: %s", exc)
            await self._post_alert(embeds.error("Update Failed", str(exc)))
        finally:
            self._updating = False

    async def _check_loop(self) -> None:
        # Read installed build on startup.
        self.current_build = await asyncio.to_thread(self._read_installed_build)
        log.info("Installed server build: %s", self.current_build)

        try:
            while self._enabled:
                await asyncio.sleep(cfg.update_check_minutes * 60)
                if not self._enabled:
                    break
                try:
                    _, latest = await self.check_now()
                    if self.has_update():
                        log.info("Update detected: %s → %s", self.current_build, latest)
                        await self._post_alert(
                            embeds.update_available(self.current_build, latest or "unknown")
                        )
                        await self.run_update_cycle()
                except Exception as exc:
                    log.warning("Update check error: %s", exc)
        except asyncio.CancelledError:
            pass

    def _read_installed_build(self) -> str:
        """Read installed build ID from Steam app manifest."""
        manifest = cfg.steamcmd_path.parent / "steamapps" / f"appmanifest_{ASA_APP_ID}.acf"
        if not manifest.exists():
            # Fallback: check in server_dir parent
            alt = cfg.server_dir.parent / "steamcmd" / "steamapps" / f"appmanifest_{ASA_APP_ID}.acf"
            if alt.exists():
                manifest = alt
            else:
                log.warning("App manifest not found: %s", manifest)
                return "unknown"

        text = manifest.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'"buildid"\s+"(\d+)"', text)
        return m.group(1) if m else "unknown"

    def _fetch_latest_build(self) -> str | None:
        """Query SteamCMD for the latest available build ID."""
        steamcmd = str(cfg.steamcmd_path)
        if not Path(steamcmd).exists():
            log.warning("SteamCMD not found: %s", steamcmd)
            return None

        try:
            result = subprocess.run(
                [
                    steamcmd,
                    "+login", "anonymous",
                    "+app_info_update", "1",
                    "+app_info_print", ASA_APP_ID,
                    "+quit",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            # Parse buildid from the output
            for line in result.stdout.splitlines():
                m = re.search(r'"buildid"\s+"(\d+)"', line)
                if m:
                    return m.group(1)
        except Exception as exc:
            log.warning("SteamCMD query failed: %s", exc)

        return None

    async def _countdown(self, total_seconds: int, reason: str = "update") -> None:
        """Broadcast countdown warnings to in-game players and Discord."""
        remaining = total_seconds
        for warn_at in sorted(_WARN_SCHEDULE, reverse=True):
            if remaining <= warn_at:
                continue
            wait = remaining - warn_at
            await asyncio.sleep(wait)
            remaining = warn_at
            label = countdown_label(remaining)
            msg = f"Server {reason} in {label}. Please find a safe spot!"
            try:
                await self.rcon.command(f"Broadcast {msg}")
            except Exception:
                pass
            await self._post_alert(embeds.update_countdown(remaining, reason))

        # Wait the final stretch
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _save_and_stop(self) -> None:
        """Save world and gracefully stop the server."""
        log.info("Saving world …")
        try:
            await self.rcon.command("Broadcast Server shutting down for update. Saving world...")
            await self.rcon.command("SaveWorld")
            await asyncio.sleep(5)  # give it a moment to flush
            await self.rcon.command("DoExit")
        except Exception as exc:
            log.warning("Graceful shutdown RCON commands failed: %s", exc)

        # Optional callback (e.g., kill the process if DoExit didn't work).
        if self._on_shutdown:
            await self._on_shutdown()

        await asyncio.sleep(10)  # wait for the process to die

    async def _run_steamcmd_update(self) -> None:
        """Run SteamCMD to update the server files."""
        log.info("Running SteamCMD update …")
        steamcmd = str(cfg.steamcmd_path)
        install_dir = str(cfg.server_dir)

        def _run():
            return subprocess.run(
                [
                    steamcmd,
                    "+login", "anonymous",
                    "+force_install_dir", install_dir,
                    "+app_update", ASA_APP_ID, "validate",
                    "+quit",
                ],
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minute max
            )

        result = await asyncio.to_thread(_run)
        if result.returncode != 0:
            log.error("SteamCMD exited with code %d:\n%s", result.returncode, result.stderr)
        else:
            log.info("SteamCMD update completed successfully.")

        # Refresh build IDs.
        self.current_build = await asyncio.to_thread(self._read_installed_build)
        self.latest_build = self.current_build

    async def _start_server(self) -> None:
        """Start the server process."""
        exe = str(cfg.server_exe)
        args = cfg.server_launch_args
        log.info("Starting server: %s %s", exe, args)

        # Fire-and-forget – the server runs independently.
        await asyncio.to_thread(
            subprocess.Popen,
            f'"{exe}" {args}',
            shell=True,
            cwd=str(cfg.server_exe.parent),
        )
        log.info("Server process started. Waiting for it to come online …")
        await asyncio.sleep(30)  # rough wait for the server to initialise

    async def _post_alert(self, embed: discord.Embed) -> None:
        if cfg.alerts_channel_id:
            ch = self.bot.get_channel(cfg.alerts_channel_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(embed=embed)
                except Exception as exc:
                    log.warning("Failed to post update alert: %s", exc)
