from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Deque, List, Optional

import discord

from config import cfg
from utils import embeds

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Event patterns (case-insensitive)
_PATTERNS = [
    ("join",  re.compile(r"(?P<name>.+?) (?:joined|connected)", re.I)),
    ("leave", re.compile(r"(?P<name>.+?) (?:left|disconnected)", re.I)),
    ("death", re.compile(r"(?P<name>.+?) was killed", re.I)),
    ("death", re.compile(r"(?P<name>.+?) (?:starved|drowned|froze)", re.I)),
]

_MAX_HISTORY = 2000  # lines kept in memory for /logs tail


class LogWatcher:

    def __init__(self, bot: discord.Client, log_path: Optional[Path] = None):
        self.bot = bot
        self.path = log_path or cfg.log_file_path
        self._task: Optional[asyncio.Task] = None
        self._history: Deque[str] = deque(maxlen=_MAX_HISTORY)
        self._offset: int = 0
        self._enabled = True

    def tail(self, n: int = 25) -> List[str]:
        """Return the last *n* log lines from memory."""
        items = list(self._history)
        return items[-n:]

    def search(self, query: str, max_results: int = 30) -> List[str]:
        """Search buffered log lines for *query* (case-insensitive)."""
        q = query.lower()
        return [l for l in self._history if q in l.lower()][:max_results]

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._watch_loop())
        log.info("Log watcher started: %s", self.path)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        log.info("Log watcher stopped.")

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
                    log.debug("Log watcher read error: %s", exc)
        except asyncio.CancelledError:
            pass

    async def _read_new_lines(self) -> None:
        if not self.path.exists():
            return

        size = self.path.stat().st_size
        if size < self._offset:
            # File was rotated / truncated – reset.
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
            await self._check_events(line)

    async def _check_events(self, line: str) -> None:
        channel = self._alerts_channel
        if channel is None:
            return

        for event_type, pattern in _PATTERNS:
            m = pattern.search(line)
            if m:
                name = m.group("name").strip()
                embed = embeds.player_event(event_type, name, detail=line.strip())
                try:
                    await channel.send(embed=embed)
                except Exception as exc:
                    log.warning("Failed to send alert: %s", exc)
                break  # one event per line

    @property
    def _alerts_channel(self) -> Optional[discord.TextChannel]:
        if cfg.alerts_channel_id:
            ch = self.bot.get_channel(cfg.alerts_channel_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        return None
