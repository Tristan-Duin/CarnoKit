"""Detects ARK server updates and applies them across the cluster.

Build detection uses a throwaway ``steamcmd`` container to read the latest
public build id, compared against the installed build id in each server's
``server-files/steamapps`` manifest.

Applying an update does NOT manage any host process: it broadcasts an
in-game countdown, saves every world, then ``docker restart``s each
container - the server image re-runs SteamCMD on start, pulling the update.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import discord

import dockerctl
from config import cfg
from utils import embeds
from utils.formatting import countdown_label

log = logging.getLogger(__name__)

# Standard countdown warning schedule (seconds before shutdown).
_WARN_SCHEDULE = [1800, 900, 300]
_SURVIVER_ROLE_MENTION = "<@&771480650581540884>"


class UpdateChecker:
    """Polls for ARK server updates and orchestrates the cluster update cycle."""

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._updating = False
        self.current_build: str = ""
        self.latest_build: Optional[str] = None
        self.installed_mods: dict[str, list[str]] = {}
        self.missing_mods: dict[str, list[str]] = {}
        self._enabled = True

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._check_loop())
        log.info("Update checker started (every %d min).", cfg.update_check_minutes)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    # ── Public helpers ────────────────────────────────────────────────────

    async def check_now(self) -> tuple[str, str | None]:
        """Check for updates right now.  Returns (current, latest)."""
        self.current_build = await asyncio.to_thread(self._read_installed_build)
        self.installed_mods = {}
        self.missing_mods = {}
        self.latest_build = await self._fetch_latest_build()
        return self.current_build, self.latest_build

    def has_game_update(self) -> bool:
        return bool(
            self.current_build
            and self.latest_build
            and self.current_build != "unknown"
            and self.current_build != self.latest_build
        )

    def has_mod_refresh(self) -> bool:
        return False

    def has_update(self) -> bool:
        return self.has_game_update()

    def should_auto_update(self) -> bool:
        return self.has_game_update()

    async def run_update_cycle(self, countdown_seconds: int | None = None) -> None:
        """Countdown -> save all -> docker restart all -> announce."""
        if self._updating:
            log.warning("Update cycle already in progress.")
            return

        self._updating = True
        try:
            reason = self._update_reason()
            countdown = countdown_seconds or (cfg.update_countdown_minutes * 60)
            await self._countdown(countdown, reason=reason)
            await self._save_all(reason=reason)
            await self._restart_all()
            await self._post_alert(embeds.success(
                "Cluster Updated & Restarted",
                f"Build `{self.latest_build or self.current_build or 'unknown'}` has been applied on all maps.",
            ))
        except Exception as exc:
            log.error("Update cycle failed: %s", exc)
            await self._post_alert(embeds.error("Update Failed", str(exc)))
        finally:
            self._updating = False

    # ── Polling loop ──────────────────────────────────────────────────────

    async def _check_loop(self) -> None:
        self.current_build = await asyncio.to_thread(self._read_installed_build)
        self.installed_mods = {}
        self.missing_mods = {}
        log.info("Installed server build: %s", self.current_build)

        try:
            while self._enabled:
                await asyncio.sleep(cfg.update_check_minutes * 60)
                if not self._enabled:
                    break
                try:
                    _, latest = await self.check_now()
                    if self.should_auto_update():
                        log.info(
                            "Update detected: build %s -> %s",
                            self.current_build,
                            latest,
                        )
                        await self._post_alert(
                            embeds.update_available(
                                self.current_build,
                                latest or "unknown",
                            )
                        )
                        await self.run_update_cycle()
                except Exception as exc:
                    log.warning("Update check error: %s", exc)
        except asyncio.CancelledError:
            pass

    # ── Build ID helpers ──────────────────────────────────────────────────

    def _read_installed_build(self) -> str:
        """Read installed build id from any server's Steam app manifest."""
        for sc in cfg.servers.values():
            manifest = sc.server_files / "steamapps" / f"appmanifest_{cfg.asa_app_id}.acf"
            if manifest.exists():
                try:
                    text = manifest.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                m = re.search(r'"buildid"\s+"(\d+)"', text)
                if m:
                    return m.group(1)
        return "unknown"

    def _update_reason(self) -> str:
        if self.has_game_update():
            return "server update"
        return "refresh"

    async def _fetch_latest_build(self) -> str | None:
        """Query the latest public build id via a throwaway steamcmd container."""
        ok, out = await dockerctl.docker_run_capture(
            [
                "run", "--rm", "steamcmd/steamcmd:latest",
                "+login", "anonymous",
                "+app_info_update", "1",
                "+app_info_print", str(cfg.asa_app_id),
                "+quit",
            ],
            timeout=240,
        )
        if not ok or not out:
            log.warning("Could not query latest build via steamcmd container.")
            return None
        # Prefer the buildid under the public branch.
        idx = out.find('"public"')
        region = out[idx:] if idx != -1 else out
        m = re.search(r'"buildid"\s+"(\d+)"', region)
        return m.group(1) if m else None

    # ── Update cycle steps ────────────────────────────────────────────────

    async def _countdown(self, total_seconds: int, reason: str = "update") -> None:
        """Broadcast countdown warnings to every server and Discord."""
        remaining = total_seconds
        for warn_at in sorted(_WARN_SCHEDULE, reverse=True):
            # `<` (not `<=`) so a countdown set exactly to a milestone (e.g. a
            # 15-minute countdown -> 900s) still fires that opening warning
            # instead of silently skipping to the next one.
            if remaining < warn_at:
                continue
            wait = remaining - warn_at
            await asyncio.sleep(wait)
            remaining = warn_at
            label = countdown_label(remaining)
            msg = f"Server {reason} in {label}. Please find a safe spot!"
            await self._broadcast_all(msg)
            await self._post_alert(
                embeds.update_countdown(remaining, reason),
                content=_SURVIVER_ROLE_MENTION,
            )

        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _broadcast_all(self, message: str) -> None:
        for key in cfg.servers:
            try:
                await self.bot.rcon_for(key).command(f"Broadcast {message}")
            except Exception:
                pass

    async def _save_all(self, reason: str = "update") -> None:
        log.info("Saving all worlds ...")
        for key in cfg.servers:
            try:
                rcon = self.bot.rcon_for(key)
                await rcon.command(f"Broadcast Server shutting down for {reason}. Saving world...")
                await rcon.command("SaveWorld")
            except Exception as exc:
                log.warning("SaveWorld failed for %s: %s", key, exc)
        await asyncio.sleep(5)  # let saves flush

    async def _restart_all(self) -> None:
        """Restart every configured server container as one cluster operation."""
        containers = [sc.container for sc in cfg.servers.values()]
        log.info("Restarting cluster containers to apply update: %s", ", ".join(containers))
        ok, out = await dockerctl.restart_containers(containers)
        if not ok:
            log.error("Cluster restart failed: %s", out)

    async def _post_alert(self, embed: discord.Embed, content: str | None = None) -> None:
        if cfg.channel_id:
            ch = self.bot.get_channel(cfg.channel_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(
                        content=content,
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                except Exception as exc:
                    log.warning("Failed to post update alert: %s", exc)
