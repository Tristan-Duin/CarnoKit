"""Tails one server's ShooterGame.log into an in-memory buffer for /logs."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Deque, List, Optional

import discord

from config import ServerConfig

log = logging.getLogger(__name__)

_MAX_HISTORY = 2000  # lines kept in memory for /logs tail


class LogWatcher:
    """Tails one ARK server log file into a rolling in-memory buffer."""

    def __init__(self, bot: discord.Client, server: ServerConfig):
        self.bot = bot
        self.server = server
        self.path = server.log_file
        self._task: Optional[asyncio.Task] = None
        self._history: Deque[str] = deque(maxlen=_MAX_HISTORY)
        self._offset: int = 0
        self._enabled = True

    # ── Public queries ────────────────────────────────────────────────────

    def tail(self, n: int = 25) -> List[str]:
        """Return the last *n* log lines from memory."""
        items = list(self._history)
        return items[-n:]

    def search(self, query: str, max_results: int = 30) -> List[str]:
        """Search buffered log lines for *query* (case-insensitive)."""
        q = query.lower()
        return [l for l in self._history if q in l.lower()][:max_results]

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._watch_loop())
        log.info("Log watcher started for %s: %s", self.server.name, self.path)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        log.info("Log watcher stopped for %s.", self.server.name)

    # ── Internals ─────────────────────────────────────────────────────────

    async def _watch_loop(self) -> None:
        # On first start, seek to end of file so we don't replay old events.
        try:
            if self.path.exists():
                self._offset = self.path.stat().st_size
        except Exception:
            self._offset = 0

        try:
            while self._enabled:
                await asyncio.sleep(3)
                if not self._enabled:
                    break
                try:
                    await self._read_new_lines()
                except Exception as exc:
                    log.debug("Log watcher read error (%s): %s", self.server.name, exc)
        except asyncio.CancelledError:
            pass

    async def _read_new_lines(self) -> None:
        if not self.path.exists():
            return

        size = self.path.stat().st_size
        if size < self._offset:
            # File was rotated / truncated - reset.
            self._offset = 0

        if size == self._offset:
            return  # no new data

        def _read():
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                data = f.read()
            return data

        data = await asyncio.to_thread(_read)
        self._offset = size

        new_lines = [l for l in data.splitlines() if l.strip()]
        for line in new_lines:
            self._history.append(line)
