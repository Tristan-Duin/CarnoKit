"""Formatting helpers used across embeds and cogs."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List


def relative_time(dt: datetime) -> str:
    """Return a human-friendly relative timestamp like '3m ago'."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m ago"
    days = hours // 24
    return f"{days}d {hours % 24}h ago"


def truncate(text: str, max_len: int = 1024) -> str:
    """Truncate text to fit within a Discord embed field."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "…"


def code_block(text: str, lang: str = "") -> str:
    """Wrap text in a Discord code block."""
    return f"```{lang}\n{text}\n```"


def parse_player_line(line: str) -> dict | None:
    """Parse a single line from the ListPlayers RCON response.

    ARK format:  ``0. PlayerName, EOS_<hex> (EOS)``
    or legacy:   ``0. PlayerName, 76561198012345678``

    Returns a dict with keys: index, name, id  – or None on parse failure.
    """
    # Modern EOS format
    m = re.match(r"(\d+)\.\s+(.+?),\s+(EOS_[0-9a-f]+|[0-9]{17})", line.strip())
    if m:
        return {"index": int(m.group(1)), "name": m.group(2).strip(), "id": m.group(3)}

    # Fallback: try less strict parsing
    m = re.match(r"(\d+)\.\s+(.+?),\s+(\S+)", line.strip())
    if m:
        return {"index": int(m.group(1)), "name": m.group(2).strip(), "id": m.group(3)}

    return None


def parse_player_list(raw: str) -> List[dict]:
    """Parse the full ListPlayers RCON response into a list of player dicts."""
    players = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        info = parse_player_line(line)
        if info:
            players.append(info)
    return players


def player_table(players: List[dict]) -> str:
    """Format a list of player dicts into a Discord-friendly display."""
    if not players:
        return "No players online."

    lines = []
    for p in players:
        lines.append(f"`{p['index']}.` **{p['name']}** — `{p['id']}`")
    return "\n".join(lines)


def countdown_label(seconds: int) -> str:
    """Return a human-readable countdown string."""
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    if seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{seconds}s"
