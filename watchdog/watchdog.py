"""
ARK Cluster Watchdog

Monitors every server in the cluster over RCON and keeps the containers
alive. Unlike a process watchdog, it never manages OS processes - it asks
Docker to restart an unresponsive container.

Features:
  - Per-server RCON health probe; restarts the container after repeated failures
  - Per-server circuit breaker: stops restarting after repeated rapid restarts
  - Optional memory-based preemptive restarts with in-game warnings
  - Boot grace so first launches / updates are not interrupted
  - Crash/restart history logging

Usage:
    py watchdog.py                     # Run with the shared config.ini
    py watchdog.py --config my.ini     # Run with a custom config
    py watchdog.py --dry-run           # Monitor only, don't restart anything
"""

from __future__ import annotations

import argparse
import configparser
import json
import logging
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Deque, Dict, List, Optional

import rcon as rcon_client

log = logging.getLogger("watchdog")

CRASH_HISTORY_FILE = "crash_history.json"


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class ServerCfg:
    key: str
    name: str
    container: str
    rcon_port: int


class Config:
    """Parsed watchdog configuration from the shared config.ini."""

    def __init__(self, path: Path):
        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")

        # [cluster]
        self.rcon_host = cp.get("cluster", "rcon_host", fallback="127.0.0.1")
        self.rcon_password = cp.get("cluster", "admin_password", fallback="")

        # [watchdog]
        self.poll_seconds = cp.getint("watchdog", "poll_seconds", fallback=30)
        self.fail_threshold = cp.getint("watchdog", "fail_threshold", fallback=3)
        self.max_restarts = cp.getint("watchdog", "max_restarts", fallback=3)
        self.restart_window_minutes = cp.getint("watchdog", "restart_window_minutes", fallback=30)
        self.cooldown_minutes = cp.getint("watchdog", "cooldown_minutes", fallback=30)
        self.max_memory_mb = cp.getint("watchdog", "max_memory_mb", fallback=0)
        self.memory_poll_seconds = cp.getint("watchdog", "memory_poll_seconds", fallback=60)
        self.memory_restart_countdown_minutes = cp.getint(
            "watchdog", "memory_restart_countdown_minutes", fallback=5
        )
        self.boot_grace_seconds = cp.getint("watchdog", "boot_grace_seconds", fallback=300)
        self.log_file = Path(cp.get("watchdog", "log_file", fallback="watchdog.log"))

        # [servers] + [server.<key>]
        self.servers: List[ServerCfg] = []
        raw_list = cp.get("servers", "list", fallback="")
        for key in [k.strip() for k in raw_list.split(",") if k.strip()]:
            section = f"server.{key}"
            if not cp.has_section(section):
                continue
            self.servers.append(
                ServerCfg(
                    key=key,
                    name=cp.get(section, "name", fallback=key),
                    container=cp.get(section, "container", fallback=f"asa-{key}"),
                    rcon_port=cp.getint(section, "rcon_port", fallback=27020),
                )
            )

    @property
    def rcon_enabled(self) -> bool:
        return bool(self.rcon_password)


# ── Per-server runtime state ────────────────────────────────────────────────────

@dataclass
class ServerState:
    fails: int = 0
    seen_alive: bool = False
    suppress_until: float = 0.0       # epoch; skip checks while booting/restarting
    cooldown_until: Optional[datetime] = None
    last_memory_check: float = 0.0
    restart_times: Deque[datetime] = field(default_factory=deque)

    def recent_restarts(self, window_minutes: int) -> int:
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        while self.restart_times and self.restart_times[0] < cutoff:
            self.restart_times.popleft()
        return len(self.restart_times)


# ── Crash / restart history ─────────────────────────────────────────────────────

class CrashHistory:
    """Persistent restart-event log (shared across all servers)."""

    def __init__(self, path: Path):
        self.path = path
        self.events: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.events = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.events = []

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.events, indent=2), encoding="utf-8")

    def record(self, server: str, reason: str, memory_mb: int = 0) -> None:
        event = {
            "time": datetime.now().isoformat(),
            "server": server,
            "reason": reason,
            "memory_mb": memory_mb,
        }
        self.events.append(event)
        self._save()
        log.info("Recorded %s for %s (mem=%dMB)", reason, server, memory_mb)


# ── Docker helpers ───────────────────────────────────────────────────────────────

def docker_restart(container: str, *, dry_run: bool) -> bool:
    if dry_run:
        log.info("[DRY RUN] Would 'docker restart %s'", container)
        return True
    try:
        r = subprocess.run(
            ["docker", "restart", container],
            capture_output=True, text=True, timeout=900,
        )
        if r.returncode != 0:
            log.error("docker restart %s failed: %s", container, r.stderr.strip())
            return False
        log.info("Restarted container %s", container)
        return True
    except Exception as exc:
        log.error("docker restart %s error: %s", container, exc)
        return False


def container_memory_mb(container: str) -> int:
    try:
        r = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0 or not r.stdout:
            return 0
        used = r.stdout.split("/")[0].strip()
        return _parse_mem_to_mb(used)
    except Exception:
        return 0


def _parse_mem_to_mb(value: str) -> int:
    value = value.strip()
    units = {
        "B": 1 / (1024 * 1024), "KIB": 1 / 1024, "MIB": 1.0, "GIB": 1024.0,
        "KB": 1 / 1024, "MB": 1.0, "GB": 1024.0, "TIB": 1024.0 * 1024,
    }
    num = ""
    for ch in value:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            break
    unit = value[len(num):].strip().upper()
    try:
        n = float(num)
    except ValueError:
        return 0
    return int(n * units.get(unit, 1.0))


# ── RCON warning helpers ─────────────────────────────────────────────────────────

def warn_players(cfg: Config, server: ServerCfg, message: str) -> None:
    if not cfg.rcon_enabled:
        return
    try:
        rcon_client.broadcast(cfg.rcon_host, server.rcon_port, cfg.rcon_password, message)
        log.info("[%s] Broadcast: %s", server.name, message)
    except Exception as exc:
        log.debug("RCON broadcast failed for %s: %s", server.name, exc)


def countdown_then_save(cfg: Config, server: ServerCfg, total_minutes: int, reason: str) -> None:
    """Broadcast a countdown, then SaveWorld (caller restarts the container)."""
    warnings = [
        (total_minutes * 60, f"{total_minutes}m"),
        (300, "5m"), (60, "1m"), (30, "30s"), (10, "10s"),
    ]
    warnings = [(s, l) for s, l in warnings if s <= total_minutes * 60]
    warnings.sort(reverse=True)

    remaining = total_minutes * 60
    for warn_at, label in warnings:
        if remaining <= warn_at:
            continue
        time.sleep(remaining - warn_at)
        remaining = warn_at
        warn_players(cfg, server, f"Server {reason} in {label}. Find a safe spot!")
    if remaining > 0:
        time.sleep(remaining)

    if cfg.rcon_enabled:
        try:
            rcon_client.save_world(cfg.rcon_host, server.rcon_port, cfg.rcon_password)
            time.sleep(5)
        except Exception:
            pass


# ── Main watchdog loop ───────────────────────────────────────────────────────────

def run(cfg: Config, *, dry_run: bool = False) -> None:
    history = CrashHistory(Path(CRASH_HISTORY_FILE))
    states: Dict[str, ServerState] = {s.key: ServerState() for s in cfg.servers}

    log.info("=" * 60)
    log.info("ARK Cluster Watchdog started")
    log.info("  Servers: %s", ", ".join(s.name for s in cfg.servers) or "(none)")
    log.info("  Poll interval: %ds  Fail threshold: %d", cfg.poll_seconds, cfg.fail_threshold)
    log.info("  Circuit breaker: %d restarts / %d min, cooldown %d min",
             cfg.max_restarts, cfg.restart_window_minutes, cfg.cooldown_minutes)
    if cfg.max_memory_mb > 0:
        log.info("  Memory limit: %d MB (check every %ds)", cfg.max_memory_mb, cfg.memory_poll_seconds)
    else:
        log.info("  Memory limit: disabled")
    log.info("  RCON: %s   Dry run: %s", "enabled" if cfg.rcon_enabled else "disabled", dry_run)
    log.info("=" * 60)

    if not cfg.servers:
        log.error("No servers configured; nothing to watch.")
        return

    while True:
        for server in cfg.servers:
            st = states[server.key]
            now = time.time()

            # Skip while a recent (re)start is still booting.
            if now < st.suppress_until:
                continue

            alive = rcon_client.is_alive(cfg.rcon_host, server.rcon_port, cfg.rcon_password)

            if alive:
                if not st.seen_alive:
                    log.info("[%s] First successful contact.", server.name)
                st.seen_alive = True
                st.fails = 0

                # Memory check (optional)
                if cfg.max_memory_mb > 0 and (now - st.last_memory_check) >= cfg.memory_poll_seconds:
                    st.last_memory_check = now
                    mem = container_memory_mb(server.container)
                    if mem > 0:
                        log.debug("[%s] Memory %d/%d MB", server.name, mem, cfg.max_memory_mb)
                        if mem >= cfg.max_memory_mb:
                            log.warning("[%s] Memory %d MB >= limit %d MB; preemptive restart.",
                                        server.name, mem, cfg.max_memory_mb)
                            history.record(server.name, "memory_limit", memory_mb=mem)
                            if not dry_run:
                                countdown_then_save(
                                    cfg, server, cfg.memory_restart_countdown_minutes, "memory restart"
                                )
                                docker_restart(server.container, dry_run=dry_run)
                            else:
                                log.info("[DRY RUN] Would memory-restart %s", server.name)
                            st.restart_times.append(datetime.now())
                            st.suppress_until = time.time() + cfg.boot_grace_seconds
                continue

            # ── Not alive ────────────────────────────────────────────────
            if not st.seen_alive:
                # Never seen up yet - it's likely still on first boot. Wait.
                log.info("[%s] Waiting for first contact (booting?)...", server.name)
                continue

            st.fails += 1
            log.warning("[%s] RCON probe failed (%d/%d).", server.name, st.fails, cfg.fail_threshold)
            if st.fails < cfg.fail_threshold:
                continue

            # Circuit breaker
            if st.cooldown_until and datetime.now() < st.cooldown_until:
                remaining = int((st.cooldown_until - datetime.now()).total_seconds())
                if remaining % 60 < cfg.poll_seconds:
                    log.info("[%s] In cooldown, %ds remaining.", server.name, remaining)
                continue

            recent = st.recent_restarts(cfg.restart_window_minutes)
            if recent >= cfg.max_restarts:
                st.cooldown_until = datetime.now() + timedelta(minutes=cfg.cooldown_minutes)
                log.error(
                    "[%s] Circuit breaker tripped: %d restarts in %d min. Cooling down %d min.",
                    server.name, recent, cfg.restart_window_minutes, cfg.cooldown_minutes,
                )
                continue

            # Restart the container.
            log.warning("[%s] Unresponsive - restarting container %s.", server.name, server.container)
            history.record(server.name, "unresponsive")
            docker_restart(server.container, dry_run=dry_run)
            st.restart_times.append(datetime.now())
            st.fails = 0
            st.cooldown_until = None
            st.suppress_until = time.time() + cfg.boot_grace_seconds

        time.sleep(cfg.poll_seconds)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="ARK Cluster Watchdog")
    ap.add_argument(
        "--config", type=Path,
        default=Path(__file__).resolve().parent.parent / "config.ini",
        help="Path to config.ini (default: ../config.ini)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Monitor and log only, don't actually restart anything",
    )
    args = ap.parse_args()

    if not args.config.exists():
        print(f"Config not found: {args.config}")
        sys.exit(1)

    cfg = Config(args.config)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if cfg.log_file:
        try:
            cfg.log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(cfg.log_file, encoding="utf-8"))
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

    try:
        run(cfg, dry_run=args.dry_run)
    except KeyboardInterrupt:
        log.info("Watchdog stopped by user.")


if __name__ == "__main__":
    main()
