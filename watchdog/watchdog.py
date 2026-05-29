from __future__ import annotations

import argparse
import configparser
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import psutil
except ImportError:
    print("psutil is required. Install it with: pip install psutil")
    sys.exit(1)

import rcon as rcon_client

log = logging.getLogger("watchdog")

CRASH_HISTORY_FILE = "crash_history.json"

class Config:
    """Parsed watchdog configuration from the shared config.ini."""

    def __init__(self, path: Path):
        cp = configparser.ConfigParser()
        cp.read(path, encoding="utf-8")

        # [server] — derive exe and launch args from shared server settings
        server_dir = Path(cp.get("server", "dir", fallback="C:/ASA/server"))
        self.exe = server_dir / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"  # binary name is fixed

        # Build launch args from server settings
        s_map = cp.get("server", "map", fallback="TheIsland_WP")
        s_name = cp.get("server", "session_name", fallback="ArkServer")
        s_jpw = cp.get("server", "join_password", fallback="")
        s_apw = cp.get("server", "admin_password", fallback="")
        s_max = cp.get("server", "max_players", fallback="70")
        rcon_port = cp.get("rcon", "port", fallback="27020")
        parts = [
            f"{s_map}?listen",
            f"?SessionName={s_name}",
            f"?Port=7777?QueryPort=27015",
            f"?MaxPlayers={s_max}",
            f"?ServerAdminPassword={s_apw}",
            f"?RCONPort={rcon_port}?RCONEnabled=True",
        ]
        if s_jpw:
            parts.append(f"?ServerPassword={s_jpw}")
        self.args = "".join(parts) + " -NoBattlEye -log"

        # [watchdog]
        self.poll_seconds = cp.getint("watchdog", "poll_seconds", fallback=10)
        self.restart_delay = cp.getint("watchdog", "restart_delay", fallback=15)
        self.max_crashes = cp.getint("watchdog", "max_crashes", fallback=3)
        self.crash_window_minutes = cp.getint("watchdog", "crash_window_minutes", fallback=10)
        self.cooldown_minutes = cp.getint("watchdog", "cooldown_minutes", fallback=30)
        self.max_memory_mb = cp.getint("watchdog", "max_memory_mb", fallback=0)
        self.memory_poll_seconds = cp.getint("watchdog", "memory_poll_seconds", fallback=60)
        self.memory_restart_countdown_minutes = cp.getint(
            "watchdog", "memory_restart_countdown_minutes", fallback=5
        )
        self.log_file = Path(cp.get("watchdog", "log_file", fallback="watchdog.log"))
        self.log_days = cp.getint("watchdog", "log_days", fallback=30)

        # [rcon]
        self.rcon_host = cp.get("rcon", "host", fallback="127.0.0.1")
        self.rcon_port = cp.getint("rcon", "port", fallback=27020)
        self.rcon_password = cp.get("rcon", "password", fallback="")

    @property
    def rcon_enabled(self) -> bool:
        return bool(self.rcon_password)

class CrashHistory:
    """Persistent crash event log."""

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

    def record(self, reason: str, uptime_seconds: int = 0, memory_mb: int = 0) -> None:
        event = {
            "time": datetime.now().isoformat(),
            "reason": reason,
            "uptime_seconds": uptime_seconds,
            "memory_mb": memory_mb,
        }
        self.events.append(event)
        self._save()
        log.info("Crash recorded: %s (uptime=%ds, mem=%dMB)", reason, uptime_seconds, memory_mb)

    def recent_count(self, window_minutes: int) -> int:
        """Count crashes within the last N minutes."""
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        count = 0
        for e in reversed(self.events):
            try:
                t = datetime.fromisoformat(e["time"])
                if t >= cutoff:
                    count += 1
                else:
                    break
            except Exception:
                continue
        return count


def find_server_process(exe_name: str = "ArkAscendedServer.exe") -> Optional[psutil.Process]:
    """Find the running server process."""
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == exe_name.lower():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def get_memory_mb(proc: psutil.Process) -> int:
    """Get process memory usage in MB."""
    try:
        return int(proc.memory_info().rss / (1024 * 1024))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0


def start_server(cfg: Config) -> subprocess.Popen:
    """Start the server process."""
    cmd = f'"{cfg.exe}" {cfg.args}'
    log.info("Starting server: %s", cmd)
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=str(cfg.exe.parent),
    )
    log.info("Server process started (PID %d)", proc.pid)
    return proc


def warn_players(cfg: Config, message: str) -> None:
    """Send an in-game broadcast warning via RCON."""
    if not cfg.rcon_enabled:
        return
    try:
        rcon_client.broadcast(cfg.rcon_host, cfg.rcon_port, cfg.rcon_password, message)
        log.info("Broadcast: %s", message)
    except Exception as exc:
        log.debug("RCON broadcast failed: %s", exc)


def graceful_shutdown(cfg: Config) -> None:
    """Save world and shut down the server gracefully via RCON."""
    if not cfg.rcon_enabled:
        return
    try:
        rcon_client.broadcast(
            cfg.rcon_host, cfg.rcon_port, cfg.rcon_password,
            "Server restarting now. Saving world..."
        )
        time.sleep(1)
        rcon_client.save_world(cfg.rcon_host, cfg.rcon_port, cfg.rcon_password)
        time.sleep(5)
        rcon_client.shutdown(cfg.rcon_host, cfg.rcon_port, cfg.rcon_password)
    except Exception as exc:
        log.debug("RCON graceful shutdown failed: %s", exc)


def countdown_restart(cfg: Config, total_minutes: int, reason: str = "restart") -> None:
    """Run a countdown with broadcast warnings, then graceful shutdown."""
    warnings = [
        (total_minutes * 60, f"{total_minutes}m"),
        (300, "5m"),
        (60, "1m"),
        (30, "30s"),
        (10, "10s"),
    ]
    # Filter to warnings that fit within our countdown
    warnings = [(s, l) for s, l in warnings if s <= total_minutes * 60]
    warnings.sort(reverse=True)

    remaining = total_minutes * 60
    for warn_at, label in warnings:
        if remaining <= warn_at:
            continue
        wait = remaining - warn_at
        time.sleep(wait)
        remaining = warn_at
        warn_players(cfg, f"Server {reason} in {label}. Find a safe spot!")

    if remaining > 0:
        time.sleep(remaining)

    graceful_shutdown(cfg)


def run(cfg: Config, *, dry_run: bool = False) -> None:
    """Main watchdog loop."""
    history = CrashHistory(Path(CRASH_HISTORY_FILE))
    server_start_time: Optional[datetime] = None
    in_cooldown = False
    cooldown_until: Optional[datetime] = None
    last_memory_check = time.time()

    log.info("=" * 60)
    log.info("Server Watchdog started")
    log.info("  Executable: %s", cfg.exe)
    log.info("  Poll interval: %ds", cfg.poll_seconds)
    log.info("  Circuit breaker: %d crashes in %d min", cfg.max_crashes, cfg.crash_window_minutes)
    if cfg.max_memory_mb > 0:
        log.info("  Memory limit: %d MB (check every %ds)", cfg.max_memory_mb, cfg.memory_poll_seconds)
    else:
        log.info("  Memory limit: disabled")
    log.info("  RCON warnings: %s", "enabled" if cfg.rcon_enabled else "disabled")
    log.info("  Dry run: %s", dry_run)
    log.info("=" * 60)

    while True:
        proc = find_server_process()

        if proc is not None:
            if server_start_time is None:
                server_start_time = datetime.now()
                in_cooldown = False
                log.info("Server detected (PID %d)", proc.pid)

            # Memory check
            if cfg.max_memory_mb > 0 and (time.time() - last_memory_check) >= cfg.memory_poll_seconds:
                last_memory_check = time.time()
                mem_mb = get_memory_mb(proc)

                if mem_mb > 0:
                    log.debug("Memory: %d MB / %d MB limit", mem_mb, cfg.max_memory_mb)

                    if mem_mb >= cfg.max_memory_mb:
                        uptime = int((datetime.now() - server_start_time).total_seconds())
                        log.warning(
                            "Memory limit exceeded: %d MB >= %d MB (uptime: %ds). "
                            "Starting preemptive restart.",
                            mem_mb, cfg.max_memory_mb, uptime,
                        )
                        history.record("memory_limit", uptime_seconds=uptime, memory_mb=mem_mb)

                        if not dry_run:
                            countdown_restart(
                                cfg,
                                cfg.memory_restart_countdown_minutes,
                                reason="memory restart",
                            )
                            # Wait for process to die
                            try:
                                proc.wait(timeout=30)
                            except Exception:
                                try:
                                    proc.kill()
                                except Exception:
                                    pass

                        server_start_time = None
                        continue

            time.sleep(cfg.poll_seconds)
            continue

        # If we were tracking it, this is a crash
        if server_start_time is not None:
            uptime = int((datetime.now() - server_start_time).total_seconds())
            log.warning("Server process gone. Uptime was %ds.", uptime)
            history.record("crash", uptime_seconds=uptime)
            server_start_time = None

        # Check circuit breaker
        recent = history.recent_count(cfg.crash_window_minutes)
        if recent >= cfg.max_crashes:
            if not in_cooldown:
                in_cooldown = True
                cooldown_until = datetime.now() + timedelta(minutes=cfg.cooldown_minutes)
                log.error(
                    "Circuit breaker tripped: %d crashes in %d minutes. "
                    "Waiting %d minutes before retrying.",
                    recent, cfg.crash_window_minutes, cfg.cooldown_minutes,
                )

            if cooldown_until and datetime.now() < cooldown_until:
                remaining = int((cooldown_until - datetime.now()).total_seconds())
                if remaining % 60 == 0:
                    log.info("Cooldown: %d seconds remaining", remaining)
                time.sleep(cfg.poll_seconds)
                continue
            else:
                log.info("Cooldown expired. Resuming restart attempts.")
                in_cooldown = False

        # Wait before restarting (lets crash dumps finish writing)
        if not dry_run:
            log.info("Waiting %ds before restart...", cfg.restart_delay)
            time.sleep(cfg.restart_delay)

            if not find_server_process():
                start_server(cfg)
                server_start_time = datetime.now()
                # Give the server time to start before polling again
                log.info("Waiting 60s for server to initialize...")
                time.sleep(60)
        else:
            log.info("[DRY RUN] Would restart server now.")
            time.sleep(cfg.poll_seconds)


def main():
    ap = argparse.ArgumentParser(description="CarnoKit Server Watchdog")
    ap.add_argument(
        "--config", type=Path,
        default=Path(__file__).resolve().parent.parent / "config.ini",
        help="Path to config.ini (default: C:\\ASA\\config.ini)",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Monitor and log only, don't actually restart the server",
    )
    args = ap.parse_args()

    if not args.config.exists():
        print(f"Config not found: {args.config}")
        print("Copy config.ini and edit it for your server.")
        sys.exit(1)

    cfg = Config(args.config)

    # Setup logging
    handlers = [logging.StreamHandler()]
    if cfg.log_file:
        handlers.append(logging.FileHandler(cfg.log_file, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

    # Validate
    if not cfg.exe.exists():
        log.error("Server executable not found: %s", cfg.exe)
        sys.exit(1)

    try:
        run(cfg, dry_run=args.dry_run)
    except KeyboardInterrupt:
        log.info("Watchdog stopped by user.")


if __name__ == "__main__":
    main()
