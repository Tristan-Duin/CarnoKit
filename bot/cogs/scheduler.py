from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from croniter import croniter
from discord import app_commands
from discord.ext import commands, tasks

from config import cfg
from rcon.client import RconClient
from utils import embeds
from utils.formatting import countdown_label
from utils.permissions import require_admin

log = logging.getLogger(__name__)


class _Schedule:

    def __init__(
        self,
        *,
        id: str,
        type: str,
        cron: str = "",
        interval: int = 0,
        message: str = "",
        enabled: bool = True,
    ):
        self.id = id
        self.type = type          # "auto-save" | "restart" | "broadcast"
        self.cron = cron          # cron expression (for restart / broadcast)
        self.interval = interval  # seconds (for auto-save)
        self.message = message
        self.enabled = enabled
        self.task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "cron": self.cron,
            "interval": self.interval,
            "message": self.message,
            "enabled": self.enabled,
        }


class SchedulerCog(commands.GroupCog, group_name="schedule"):

    def __init__(self, bot: commands.Bot, rcon: RconClient):
        self.bot = bot
        self.rcon = rcon
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

    @app_commands.command(name="auto-save", description="Set auto-save interval in minutes (0 to disable)")
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
            embed=embeds.success("Auto-Save", f"World will auto-save every **{minutes}** minutes.")
        )

    @app_commands.command(name="restart", description="Schedule a recurring server restart (cron syntax)")
    @app_commands.describe(cron="Cron expression, e.g. '0 4 * * *' for daily at 4 AM")
    @require_admin
    async def restart(self, interaction: discord.Interaction, cron: str):
        if not croniter.is_valid(cron):
            return await interaction.response.send_message(
                embed=embeds.error("Invalid Cron", f"`{cron}` is not a valid cron expression.")
            )

        sid = str(uuid.uuid4())[:8]
        sched = _Schedule(id=sid, type="restart", cron=cron)
        self._schedules[sid] = sched
        sched.task = asyncio.create_task(self._cron_restart_loop(sched))
        self._save_state()

        nxt = croniter(cron, datetime.now()).get_next(datetime)
        await interaction.response.send_message(
            embed=embeds.success(
                "Restart Scheduled",
                f"ID: `{sid}`\nCron: `{cron}`\nNext run: {nxt.strftime('%Y-%m-%d %H:%M')}",
            )
        )

    @app_commands.command(name="broadcast", description="Schedule a recurring broadcast message (cron syntax)")
    @app_commands.describe(cron="Cron expression", message="Message to broadcast")
    @require_admin
    async def broadcast(self, interaction: discord.Interaction, cron: str, message: str):
        if not croniter.is_valid(cron):
            return await interaction.response.send_message(
                embed=embeds.error("Invalid Cron", f"`{cron}` is not a valid cron expression.")
            )

        sid = str(uuid.uuid4())[:8]
        sched = _Schedule(id=sid, type="broadcast", cron=cron, message=message)
        self._schedules[sid] = sched
        sched.task = asyncio.create_task(self._cron_broadcast_loop(sched))
        self._save_state()

        nxt = croniter(cron, datetime.now()).get_next(datetime)
        await interaction.response.send_message(
            embed=embeds.success(
                "Broadcast Scheduled",
                f"ID: `{sid}`\nCron: `{cron}`\nMessage: {message}\nNext: {nxt.strftime('%Y-%m-%d %H:%M')}",
            )
        )

    @app_commands.command(name="list", description="Show all active schedules")
    async def list_schedules(self, interaction: discord.Interaction):
        items = [s.to_dict() for s in self._schedules.values()]
        await interaction.response.send_message(embed=embeds.schedule_list(items))

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

    def _start_auto_save(self, interval_seconds: int) -> None:
        async def _loop():
            try:
                while True:
                    await asyncio.sleep(interval_seconds)
                    try:
                        await self.rcon.ensure_connected()
                        await self.rcon.command("SaveWorld")
                        log.info("Auto-save complete.")
                    except Exception as exc:
                        log.warning("Auto-save failed: %s", exc)
            except asyncio.CancelledError:
                pass

        self._auto_save_task = asyncio.create_task(_loop())

    async def _cron_restart_loop(self, sched: _Schedule) -> None:
        """Wait for the next cron tick, then do a restart cycle."""
        try:
            while sched.enabled:
                nxt = croniter(sched.cron, datetime.now()).get_next(datetime)
                delay = (nxt - datetime.now()).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)

                # 5-minute countdown
                warnings = [300, 60, 30]
                remaining = 300
                for warn_at in warnings:
                    if remaining <= warn_at:
                        continue
                    wait = remaining - warn_at
                    await asyncio.sleep(wait)
                    remaining = warn_at
                    label = countdown_label(remaining)
                    try:
                        await self.rcon.command(f"Broadcast Server restart in {label}!")
                    except Exception:
                        pass
                if remaining > 0:
                    await asyncio.sleep(remaining)

                try:
                    await self.rcon.command("Broadcast Server restarting now...")
                    await self.rcon.command("SaveWorld")
                    await asyncio.sleep(3)
                    await self.rcon.command("DoExit")
                except Exception as exc:
                    log.warning("Scheduled restart RCON failed: %s", exc)
        except asyncio.CancelledError:
            pass

    async def _cron_broadcast_loop(self, sched: _Schedule) -> None:
        """Wait for the next cron tick, then broadcast a message."""
        try:
            while sched.enabled:
                nxt = croniter(sched.cron, datetime.now()).get_next(datetime)
                delay = (nxt - datetime.now()).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    await self.rcon.ensure_connected()
                    await self.rcon.command(f"Broadcast {sched.message}")
                except Exception as exc:
                    log.warning("Scheduled broadcast failed: %s", exc)
        except asyncio.CancelledError:
            pass

    def _save_state(self) -> None:
        data = [s.to_dict() for s in self._schedules.values()]
        cfg.schedule_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_state(self) -> None:
        if not cfg.schedule_file.exists():
            return
        try:
            data = json.loads(cfg.schedule_file.read_text(encoding="utf-8"))
            for item in data:
                sched = _Schedule(**item)
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
    rcon: RconClient = bot.rcon  # type: ignore[attr-defined]
    await bot.add_cog(SchedulerCog(bot, rcon))
