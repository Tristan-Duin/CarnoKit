"""Reusable Discord embed builders for every command category."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import discord

from .formatting import (
    code_block,
    countdown_label,
    parse_player_list,
    player_table,
    truncate,
)

# Colour palette
COLOR_OK = 0x2B9F5C
COLOR_WARN = 0xFFA500
COLOR_ERR = 0xFF4444
COLOR_INFO = 0x3498DB
COLOR_UPDATE = 0x9B59B6


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


# ── Generic helpers ───────────────────────────────────────────────────────────

def success(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=description, color=COLOR_OK).set_footer(text=_ts())


def error(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=description, color=COLOR_ERR).set_footer(text=_ts())


def warning(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=description, color=COLOR_WARN).set_footer(text=_ts())


def info(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=description, color=COLOR_INFO).set_footer(text=_ts())


# ── Server status ─────────────────────────────────────────────────────────────

def server_status(
    *,
    online: bool,
    player_count: int,
    player_list: str,
    map_name: str,
    rcon_host: str,
    rcon_port: int,
    server_name: str = "",
) -> discord.Embed:
    status = "Online" if online else "Offline"
    title = f"{server_name} - Server Status" if server_name else "Server Status"
    embed = discord.Embed(title=title, color=COLOR_OK if online else COLOR_ERR)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Players", value=str(player_count), inline=True)
    embed.add_field(name="Map", value=map_name, inline=True)
    embed.add_field(name="RCON", value=f"`{rcon_host}:{rcon_port}`", inline=True)

    if player_list.strip():
        players = parse_player_list(player_list)
        table = player_table(players)
        embed.add_field(name="Online Players", value=truncate(table, 1000), inline=False)

    embed.set_footer(text=_ts())
    return embed


# ── Player list ───────────────────────────────────────────────────────────────

def player_list_embed(raw: str) -> discord.Embed:
    players = parse_player_list(raw)
    count = len(players)
    embed = discord.Embed(
        title=f"Online Players ({count})",
        color=COLOR_INFO,
    )
    if players:
        embed.description = truncate(player_table(players), 3900)
    else:
        embed.description = "No players online."
    embed.set_footer(text=_ts())
    return embed


# ── RCON raw response ─────────────────────────────────────────────────────────

def rcon_response(command: str, response: str) -> discord.Embed:
    embed = discord.Embed(title="RCON", color=COLOR_INFO)
    embed.add_field(name="Command", value=f"`{command}`", inline=False)
    body = response if response else "(no response)"
    embed.add_field(name="Response", value=code_block(truncate(body, 1000)), inline=False)
    embed.set_footer(text=_ts())
    return embed


# ── Update / restart ──────────────────────────────────────────────────────────

def update_available(current_build: str, latest_build: str) -> discord.Embed:
    embed = discord.Embed(
        title="ARK Server Update Available",
        description=(
            f"A new server update has been detected.\n\n"
            f"**Current Build:** `{current_build}`\n"
            f"**Latest Build:**  `{latest_build}`"
        ),
        color=COLOR_UPDATE,
    )
    embed.set_footer(text=_ts())
    return embed


def update_countdown(seconds_left: int, reason: str = "update") -> discord.Embed:
    label = countdown_label(seconds_left)
    return discord.Embed(
        title=f"Server {reason.title()} in {label}",
        description=f"The server will save and shut down for a {reason} in **{label}**.",
        color=COLOR_WARN,
    ).set_footer(text=_ts())


def update_status(
    current_build: str,
    latest_build: str | None,
    auto_update: bool,
    check_interval: int,
) -> discord.Embed:
    is_current = latest_build and current_build == latest_build
    embed = discord.Embed(
        title="Update Status",
        color=COLOR_OK if is_current else COLOR_WARN,
    )
    embed.add_field(name="Installed Build", value=f"`{current_build}`", inline=True)
    embed.add_field(name="Latest Build", value=f"`{latest_build or 'unknown'}`", inline=True)
    embed.add_field(
        name="Status",
        value="Up to date" if is_current else "Update available",
        inline=True,
    )
    embed.add_field(name="Auto-Update", value="Enabled" if auto_update else "Disabled", inline=True)
    embed.add_field(name="Check Interval", value=f"{check_interval} min", inline=True)
    embed.set_footer(text=_ts())
    return embed


# ── Scheduler ─────────────────────────────────────────────────────────────────

def schedule_list(schedules: List[dict]) -> discord.Embed:
    embed = discord.Embed(title="Active Schedules", color=COLOR_INFO)
    if not schedules:
        embed.description = "No active schedules."
    else:
        lines = []
        for s in schedules:
            lines.append(f"**{s['id']}** — {s['type']} | `{s.get('cron', s.get('interval', ''))}`")
            if s.get("message"):
                lines.append(f"  └ \"{s['message']}\"")
        embed.description = "\n".join(lines)
    embed.set_footer(text=_ts())
    return embed


# ── Log entries ───────────────────────────────────────────────────────────────

def log_tail(lines: List[str], title: str = "Server Logs") -> discord.Embed:
    body = "\n".join(lines) if lines else "(no log entries)"
    embed = discord.Embed(title=title, color=COLOR_INFO)
    embed.description = code_block(truncate(body, 3900))
    embed.set_footer(text=_ts())
    return embed


# ── Alerts ────────────────────────────────────────────────────────────────────

def player_event(event_type: str, player_name: str, detail: str = "", server: str = "") -> discord.Embed:
    title = f"Player {event_type.title()}"
    if server:
        title = f"[{server}] {title}"
    embed = discord.Embed(
        title=title,
        description=f"**{player_name}**" + (f"\n{detail}" if detail else ""),
        color=COLOR_INFO if event_type == "join" else COLOR_WARN,
    )
    embed.set_footer(text=_ts())
    return embed


# ── Cluster ─────────────────────────────────────────────────────

def cluster_status(rows: List[dict]) -> discord.Embed:
    """Summarise every server in the cluster.

    Each row: {name, online, players, map, game_port}.
    """
    online_count = sum(1 for r in rows if r.get("online"))
    if rows and online_count == len(rows):
        color = COLOR_OK
    elif online_count:
        color = COLOR_WARN
    else:
        color = COLOR_ERR
    embed = discord.Embed(
        title=f"Cluster Status ({online_count}/{len(rows)} online)",
        color=color,
    )
    for r in rows:
        state = "Online" if r.get("online") else "Offline"
        players = f"{r.get('players', 0)} players" if r.get("online") else "-"
        embed.add_field(
            name=r.get("name", "?"),
            value=f"{state}\n`{r.get('map','')}`\nPort `{r.get('game_port','')}` - {players}",
            inline=True,
        )
    embed.set_footer(text=_ts())
    return embed
