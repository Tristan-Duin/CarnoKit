"""Bidirectional chat bridge between one ARK server and a Discord channel."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Optional, Set

import discord

from config import ServerConfig, cfg
from utils import embeds

if TYPE_CHECKING:
    from rcon.client import RconClient

log = logging.getLogger(__name__)

# Regex to pull player name + message from GetChat lines.
# Typical ARK format:  "PlayerName (TribeName): message here"
# or:                  "PlayerName: message here"
_CHAT_RE = re.compile(
    r"^(?P<player>.+?)\s*(?:\((?P<tribe>.+?)\))?\s*:\s*(?P<msg>.+)$"
)

# Lines from GetChat that are noise, not actual player messages.
_NOISE = {
    "server received, but no response!!",
    "no response!!",
    "",
}


class ChatBridge:
    """Polls one server's RCON GetChat and forwards to Discord, and vice versa."""

    def __init__(self, rcon: "RconClient", bot: discord.Client, server: ServerConfig):
        self.rcon = rcon
        self.bot = bot
        self.server = server
        self._task: Optional[asyncio.Task] = None
        self._seen: Set[str] = set()  # dedup fingerprints
        self._enabled = True

    @property
    def channel(self) -> Optional[discord.TextChannel]:
        cid = self.server.chat_bridge_channel_id
        if cid:
            ch = self.bot.get_channel(cid)
            if isinstance(ch, discord.TextChannel):
                return ch
        return None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._poll_loop())
        log.info("Chat bridge started for %s (poll every %ds).", self.server.name, cfg.chat_poll_seconds)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        log.info("Chat bridge stopped for %s.", self.server.name)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        if value:
            self.start()
        else:
            self.stop()

    # ── Discord → ARK ────────────────────────────────────────────────────

    async def send_to_ark(self, author: str, message: str) -> None:
        """Send a Discord message into the ARK server chat."""
        text = f"[Discord] {author}: {message}"
        await self.rcon.command(f"ServerChat {text}")

    # ── Polling loop ──────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        try:
            while self._enabled:
                await asyncio.sleep(cfg.chat_poll_seconds)
                if not self._enabled:
                    break
                try:
                    await self._fetch_and_relay()
                except Exception as exc:
                    log.warning("Chat bridge poll error (%s): %s", self.server.name, exc)
        except asyncio.CancelledError:
            pass

    async def _fetch_and_relay(self) -> None:
        channel = self.channel
        if channel is None:
            return

        raw = await self.rcon.command("GetChat")
        if not raw or not raw.strip():
            return

        for line in raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue

            # Skip ARK noise responses and bot echo.
            if line.lower() in _NOISE:
                continue
            if "[Discord]" in line:
                continue

            # Dedup: skip lines we've already relayed.
            fp = line[:120]
            if fp in self._seen:
                continue
            self._seen.add(fp)
            # Keep dedup set bounded.
            if len(self._seen) > 500:
                self._seen = set(list(self._seen)[-200:])

            m = _CHAT_RE.match(line)
            if m:
                embed = embeds.chat_message(
                    m.group("player"),
                    m.group("msg"),
                    tribe=m.group("tribe") or "",
                    server=self.server.name,
                )
                await channel.send(embed=embed)
            else:
                # Unknown format - send as plain text.
                await channel.send(f"[ARK:{self.server.name}] {line}")
