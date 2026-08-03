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
import html
import json
import logging
import re
import urllib.request
from typing import Optional

import discord

import dockerctl
from config import cfg
from utils import embeds
from utils.formatting import countdown_label

log = logging.getLogger(__name__)

# Standard countdown warning schedule (seconds before shutdown).
_WARN_SCHEDULE = [1800, 900, 300, 60]
_FINAL_SAVE_FLUSH_SECONDS = 20
_ARK_ROLE_MENTION = "<@&1526687172609179790>"
_PATCH_NOTES_URL = (
    "https://survivetheark.com/index.php?/forums/topic/"
    "708761-asa-pc-patch-notes/"
)


class UpdateChecker:
    """Polls for ARK server updates and orchestrates the cluster update cycle."""

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._task: Optional[asyncio.Task] = None
        self._updating = False
        self.current_build: str = ""
        self.installed_builds: dict[str, str] = {}
        self.latest_build: Optional[str] = None
        self.patch_notes: dict[str, object] | None = None
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
        self.installed_builds = await asyncio.to_thread(self._read_installed_builds)
        self.current_build = self._format_installed_builds(self.installed_builds)
        self.installed_mods = {}
        self.missing_mods = {}
        self.latest_build = await self._fetch_latest_build()
        if self.has_game_update():
            self.patch_notes = await asyncio.to_thread(self._fetch_patch_notes)
        else:
            self.patch_notes = None
        return self.current_build, self.latest_build

    def has_game_update(self) -> bool:
        if self.installed_builds and self.latest_build and self.latest_build != "unknown":
            return any(
                build == "unknown" or build != self.latest_build
                for build in self.installed_builds.values()
            )
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
            await self._save_all(reason=reason, flush_seconds=_FINAL_SAVE_FLUSH_SECONDS)
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
        self.installed_builds = await asyncio.to_thread(self._read_installed_builds)
        self.current_build = self._format_installed_builds(self.installed_builds)
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

    def _read_installed_builds(self) -> dict[str, str]:
        """Read installed build ids from every server's Steam app manifest."""
        builds: dict[str, str] = {}
        for key, sc in cfg.servers.items():
            manifest = sc.server_files / "steamapps" / f"appmanifest_{cfg.asa_app_id}.acf"
            builds[key] = "unknown"
            if manifest.exists():
                try:
                    text = manifest.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                m = re.search(r'"buildid"\s+"(\d+)"', text)
                if m:
                    builds[key] = m.group(1)
        return builds

    def _read_installed_build(self) -> str:
        """Read installed build ids and return a compact cluster summary."""
        return self._format_installed_builds(self._read_installed_builds())

    def _format_installed_builds(self, builds: dict[str, str]) -> str:
        """Return one build id when all maps match, otherwise a readable summary."""
        if not builds:
            return "unknown"

        unique = set(builds.values())
        if len(unique) == 1:
            return next(iter(unique))

        return "mixed (" + ", ".join(
            f"{key}:{build}" for key, build in builds.items()
        ) + ")"

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

    def _fetch_patch_notes(self) -> dict[str, object] | None:
        """Fetch a short summary of the latest official ASA PC patch notes."""
        request = urllib.request.Request(
            _PATCH_NOTES_URL,
            headers={"User-Agent": "CarnoKit/1.0 (+ARK update announcements)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw_page = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                page = raw_page.decode(charset, errors="replace")
                # The forum occasionally serves Windows-1252 punctuation while
                # declaring UTF-8. Prefer readable notes over replacement chars.
                if "�" in page:
                    page = raw_page.decode("windows-1252", errors="replace")
        except Exception as exc:
            log.warning("Could not fetch official ARK patch notes: %s", exc)
            return None

        match = re.search(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            log.warning("Official ARK patch notes did not contain JSON-LD data.")
            return None

        try:
            data = json.loads(match.group(1))
        except (TypeError, ValueError) as exc:
            log.warning("Could not parse official ARK patch notes: %s", exc)
            return None

        article = self._find_patch_article(data)
        if not article:
            return None

        raw_text = html.unescape(str(article.get("text", "")))
        lines = [re.sub(r"\s+", " ", line).strip(" \t-•") for line in raw_text.splitlines()]
        lines = [line for line in lines if line]
        start = next((i for i, line in enumerate(lines) if re.match(r"^v\d", line, re.I)), None)
        if start is None:
            return None

        heading = lines[start]
        section: list[str] = []
        for line in lines[start + 1:]:
            if re.match(r"^v\d", line, re.I):
                break
            if len(line) < 4 or line.lower().startswith("you’ll also find"):
                continue
            section.append(line)

        action_prefixes = (
            "added ", "adjusted ", "fixed ", "improved ", "increased ",
            "new ", "optimized ", "prevented ", "reduced ", "removed ",
            "updated ",
        )
        changes = [
            line for line in section
            if line.lower().startswith(action_prefixes)
        ][:6]
        if not changes:
            changes = section[:6]

        if not changes:
            return None
        return {
            "title": heading,
            "changes": changes,
            "url": str(article.get("url") or _PATCH_NOTES_URL),
        }

    def _find_patch_article(self, value: object) -> dict[str, object] | None:
        """Find the article-shaped object within the forum page's JSON-LD."""
        if isinstance(value, dict):
            if value.get("text") and value.get("headline"):
                return value
            for child in value.values():
                found = self._find_patch_article(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = self._find_patch_article(child)
                if found:
                    return found
        return None

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
            msg = f"{self._reason_label(reason)} in {label}. Please find a safe spot!"
            notes = self.patch_notes if warn_at == 900 else None
            if notes:
                msg += " Patch notes are posted in Discord."
            await self._broadcast_all(msg)
            await self._post_alert(
                embeds.update_countdown(remaining, reason, patch_notes=notes),
                content=_ARK_ROLE_MENTION,
            )
            if warn_at == 60:
                await self._save_all(
                    reason=reason,
                    flush_seconds=0,
                    broadcast_message=(
                        f"{self._reason_label(reason)} in 1 minute. "
                        "Saving world progress now..."
                    ),
                )

        if remaining > 0:
            await asyncio.sleep(remaining)

    def _reason_label(self, reason: str) -> str:
        return reason[:1].upper() + reason[1:]

    async def _broadcast_all(self, message: str) -> None:
        for key in cfg.servers:
            try:
                rcon = self.bot.rcon_for(key)
                await rcon.ensure_connected()
                await rcon.command(self._server_chat_command(message))
            except Exception as exc:
                log.warning("Update broadcast failed for %s: %s", key, exc)

    async def _save_all(
        self,
        reason: str = "update",
        *,
        flush_seconds: int = 5,
        broadcast_message: str | None = None,
    ) -> None:
        log.info("Saving all worlds ...")
        failures: list[str] = []
        for key in cfg.servers:
            try:
                rcon = self.bot.rcon_for(key)
                await rcon.ensure_connected()
                await rcon.command(self._server_chat_command(
                    broadcast_message or f"Server shutting down for {reason}. Saving world..."
                ))
                await rcon.command("SaveWorld")
            except Exception as exc:
                log.warning("SaveWorld failed for %s: %s", key, exc)
                failures.append(f"{cfg.servers[key].name}: {exc}")

        if failures:
            raise RuntimeError(
                "Aborting update because one or more worlds could not be saved: "
                + "; ".join(failures)
            )

        if flush_seconds > 0:
            await asyncio.sleep(flush_seconds)  # let saves flush

    def _server_chat_command(self, message: str) -> str:
        """Build an on-screen broadcast command for cluster notices."""
        return f"Broadcast {message.replace(chr(34), chr(39))}"

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
