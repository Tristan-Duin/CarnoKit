"""Scheduled tasks - auto-save, timed restarts, recurring broadcasts (cluster-aware)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional

import discord
from croniter import croniter
from discord import app_commands
from discord.ext import commands

import dockerctl
from config import cfg, server_choices
from utils import embeds
from utils.formatting import countdown_label
from utils.permissions import require_admin

log = logging.getLogger(__name__)


class _Schedule:
    """A single scheduled job.  ``server`` is a server key, or "" for all maps."""

    def __init__(
        self,
        *,
        id: str,
        type: str,
        cron: str = "",
        interval: int = 0,
        message: str = "",
        server: str = "",
        enabled: bool = True,
    ):
        self.id = id
        self.type = type          # "restart" | "broadcast"
        self.cron = cron
        self.interval = interval
        self.message = message
        self.server = server      # "" = whole cluster
        self.enabled = enabled
        self.task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "cron": self.cron,
            "interval": self.interval,
            "message": self.message,
            "server": self.server,
            "enabled": self.enabled,
        }


class SchedulerCog(commands.GroupCog, group_name="schedule"):
    """Manage recurring tasks for the ARK cluster."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._schedules: dict[str, _Schedule] = {}
        self._auto_save_task: Optional[asyncio.Task] = None

    async def cog_load(self) -> None:
        self._load_state()
        self._start_all()
        if cfg.auto_save_minutes > 0:
            self._start_auto_save(cfg.auto_save_minutes * 60)

    async def cog_unload(self) -> None:
        self._stop_all()
        if self._auto_save_task and not self._auto_save_task.done():
            self._auto_save_task.cancel()

    # ── Target resolution ─────────────────────────────────────────────────

    def _targets(self, server_key: str) -> List[str]:
        if server_key and server_key in cfg.servers:
            return [server_key]
        return list(cfg.servers.keys())

    def _target_label(self, server_key: str) -> str:
        if server_key and server_key in cfg.servers:
            return cfg.servers[server_key].name
        return "the whole cluster"

    # ── /schedule auto-save ───────────────────────────────────────────────

    @app_commands.command(name="auto-save", description="Set auto-save interval in minutes (0 to disable) for all maps")
    @app_commands.describe(minutes="Interval in minutes between saves (0 = off)")
    @require_admin
    async def auto_save(self, interaction: discord.Interaction, minutes: int):
        if self._auto_save_task and not self._auto_save_task.done():
            self._auto_save_task.cancel()

        if minutes <= 0:
            await interaction.response.send_message(
                embed=embeds.info("Auto-Save", "Auto-save disabled.")
            )
            return

        self._start_auto_save(minutes * 60)
        await interaction.response.send_message(
            embed=embeds.success("Auto-Save", f"Every map will auto-save every **{minutes}** minutes.")
        )

    # ── /schedule restart ─────────────────────────────────────────────────

    @app_commands.command(name="restart", description="Schedule a recurring server restart (cron syntax)")
    @app_commands.describe(cron="Cron expression, e.g. '0 4 * * *' for daily at 4 AM", server="Target map (omit = whole cluster)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def restart(self, interaction: discord.Interaction, cron: str, server: Optional[str] = None):
        if not croniter.is_valid(cron):
            return await interaction.response.send_message(
                embed=embeds.error("Invalid Cron", f"`{cron}` is not a valid cron expression.")
            )

        key = cfg.server(server).key if server else ""
        sid = str(uuid.uuid4())[:8]
        sched = _Schedule(id=sid, type="restart", cron=cron, server=key)
        self._schedules[sid] = sched
        sched.task = asyncio.create_task(self._cron_restart_loop(sched))
        self._save_state()

        nxt = croniter(cron, datetime.now()).get_next(datetime)
        await interaction.response.send_message(
            embed=embeds.success(
                "Restart Scheduled",
                f"ID: `{sid}`\nTarget: {self._target_label(key)}\nCron: `{cron}`\n"
                f"Next run: {nxt.strftime('%Y-%m-%d %H:%M')}",
            )
        )

    # ── /schedule broadcast ───────────────────────────────────────────────

    @app_commands.command(name="broadcast", description="Schedule a recurring broadcast message (cron syntax)")
    @app_commands.describe(cron="Cron expression", message="Message to broadcast", server="Target map (omit = whole cluster)")
    @app_commands.choices(server=server_choices())
    @require_admin
    async def broadcast(self, interaction: discord.Interaction, cron: str, message: str, server: Optional[str] = None):
        if not croniter.is_valid(cron):
            return await interaction.response.send_message(
                embed=embeds.error("Invalid Cron", f"`{cron}` is not a valid cron expression.")
            )

        key = cfg.server(server).key if server else ""
        sid = str(uuid.uuid4())[:8]
        sched = _Schedule(id=sid, type="broadcast", cron=cron, message=message, server=key)
        self._schedules[sid] = sched
        sched.task = asyncio.create_task(self._cron_broadcast_loop(sched))
        self._save_state()

        nxt = croniter(cron, datetime.now()).get_next(datetime)
        await interaction.response.send_message(
            embed=embeds.success(
                "Broadcast Scheduled",
                f"ID: `{sid}`\nTarget: {self._target_label(key)}\nCron: `{cron}`\n"
                f"Message: {message}\nNext: {nxt.strftime('%Y-%m-%d %H:%M')}",
            )
        )

    # ── /schedule list ────────────────────────────────────────────────────

    @app_commands.command(name="list", description="Show all active schedules")
    async def list_schedules(self, interaction: discord.Interaction):
        items = []
        for s in self._schedules.values():
            d = s.to_dict()
            d["message"] = (d.get("message") or "") + (
                f"  [target: {self._target_label(s.server)}]"
            )
            items.append(d)
        await interaction.response.send_message(embed=embeds.schedule_list(items))

    # ── /schedule cancel ──────────────────────────────────────────────────

    @app_commands.command(name="cancel", description="Cancel a scheduled task by ID")
    @app_commands.describe(id="The schedule ID to cancel")
    @require_admin
    async def cancel(self, interaction: discord.Interaction, id: str):
        sched = self._schedules.pop(id, None)
        if sched is None:
            return await interaction.response.send_message(
                embed=embeds.error("Not Found", f"No schedule with ID `{id}`.")
            )
        if sched.task and not sched.task.done():
            sched.task.cancel()
        self._save_state()
        await interaction.response.send_message(
            embed=embeds.success("Schedule Cancelled", f"Removed schedule `{id}` ({sched.type}).")
        )

    # ── Internal loops ────────────────────────────────────────────────────

    def _start_auto_save(self, interval_seconds: int) -> None:
        async def _loop():
            try:
                while True:
                    await asyncio.sleep(interval_seconds)
                    for key in cfg.servers:
                        try:
                            rcon = self.bot.rcon_for(key)  # type: ignore[attr-defined]
                            await rcon.ensure_connected()
                            await rcon.command("SaveWorld")
                        except Exception as exc:
                            log.warning("Auto-save failed for %s: %s", key, exc)
                    log.info("Auto-save complete (all servers).")
            except asyncio.CancelledError:
                pass

        self._auto_save_task = asyncio.create_task(_loop())

    async def _cron_restart_loop(self, sched: _Schedule) -> None:
        """Wait for the next cron tick, then run a restart cycle on the targets."""
        try:
            while sched.enabled:
                nxt = croniter(sched.cron, datetime.now()).get_next(datetime)
                delay = (nxt - datetime.now()).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)

                targets = self._targets(sched.server)

                # 5-minute countdown
                warnings = [300, 60, 30]
                remaining = 300
                for warn_at in warnings:
                    if remaining <= warn_at:
                        continue
                    await asyncio.sleep(remaining - warn_at)
                    remaining = warn_at
                    label = countdown_label(remaining)
                    for key in targets:
                        try:
                            await self.bot.rcon_for(key).command(  # type: ignore[attr-defined]
                                f"Broadcast Server restart in {label}!"
                            )
                        except Exception:
                            pass
                if remaining > 0:
                    await asyncio.sleep(remaining)

                # Save + restart each target container.
                for key in targets:
                    sc = cfg.servers[key]
                    try:
                        rcon = self.bot.rcon_for(key)  # type: ignore[attr-defined]
                        await rcon.command("Broadcast Server restarting now...")
                        await rcon.command("SaveWorld")
                        await asyncio.sleep(3)
                    except Exception as exc:
                        log.warning("Scheduled restart RCON failed for %s: %s", key, exc)
                    ok, out = await dockerctl.restart_container(sc.container)
                    if not ok:
                        log.error("Scheduled restart failed for %s: %s", sc.container, out)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    async def _cron_broadcast_loop(self, sched: _Schedule) -> None:
        """Wait for the next cron tick, then broadcast a message to the targets."""
        try:
            while sched.enabled:
                nxt = croniter(sched.cron, datetime.now()).get_next(datetime)
                delay = (nxt - datetime.now()).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
                for key in self._targets(sched.server):
                    try:
                        rcon = self.bot.rcon_for(key)  # type: ignore[attr-defined]
                        await rcon.ensure_connected()
                        await rcon.command(f"Broadcast {sched.message}")
                    except Exception as exc:
                        log.warning("Scheduled broadcast failed for %s: %s", key, exc)
        except asyncio.CancelledError:
            pass

    # ── Persistence ───────────────────────────────────────────────────────

    def _save_state(self) -> None:
        data = [s.to_dict() for s in self._schedules.values()]
        cfg.schedule_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_state(self) -> None:
        if not cfg.schedule_file.exists():
            return
        try:
            data = json.loads(cfg.schedule_file.read_text(encoding="utf-8"))
            for item in data:
                sched = _Schedule(
                    id=item["id"],
                    type=item["type"],
                    cron=item.get("cron", ""),
                    interval=item.get("interval", 0),
                    message=item.get("message", ""),
                    server=item.get("server", ""),
                    enabled=item.get("enabled", True),
                )
                self._schedules[sched.id] = sched
        except Exception as exc:
            log.warning("Failed to load schedules: %s", exc)

    def _start_all(self) -> None:
        for sched in self._schedules.values():
            if sched.type == "restart":
                sched.task = asyncio.create_task(self._cron_restart_loop(sched))
            elif sched.type == "broadcast":
                sched.task = asyncio.create_task(self._cron_broadcast_loop(sched))

    def _stop_all(self) -> None:
        for sched in self._schedules.values():
            if sched.task and not sched.task.done():
                sched.task.cancel()


async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulerCog(bot))
