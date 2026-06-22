"""Thin async wrappers around the ``docker`` CLI.

The bot and the updater use these to restart cluster containers (which is
how an ASA update is applied: the image re-runs SteamCMD on container
start) without doing any host-side process management.

The process running the bot must be able to run ``docker`` - i.e. run as
root or as a user in the ``docker`` group (the systemd unit documents this).
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def _run(cmd: list[str], timeout: float) -> tuple[bool, str]:
    """Run a command, returning (ok, combined_output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return False, "docker executable not found on PATH"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return False, f"command timed out after {timeout:.0f}s"

    text = (out or b"").decode("utf-8", errors="replace").strip()
    ok = proc.returncode == 0
    if not ok:
        log.warning("docker command failed (rc=%s): %s -> %s", proc.returncode, " ".join(cmd), text)
    return ok, text


async def docker_run_capture(args: list[str], timeout: float = 240) -> tuple[bool, str]:
    """Run an arbitrary ``docker <args...>`` command and capture its output."""
    return await _run(["docker", *args], timeout)


async def restart_container(name: str, timeout: float = 900) -> tuple[bool, str]:
    """``docker restart <name>`` - triggers SteamCMD update + clean reboot."""
    return await _run(["docker", "restart", name], timeout)


async def container_running(name: str, timeout: float = 30) -> bool:
    ok, out = await _run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name], timeout
    )
    return ok and out.strip() == "true"


async def container_memory_mb(name: str, timeout: float = 30) -> int:
    """Return container RSS in MB via ``docker stats`` (0 if unavailable)."""
    ok, out = await _run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
        timeout,
    )
    if not ok or not out:
        return 0
    # out looks like "12.3GiB / 64GiB"; take the part before the slash.
    used = out.split("/")[0].strip()
    return _parse_mem_to_mb(used)


def _parse_mem_to_mb(value: str) -> int:
    value = value.strip()
    units = {"B": 1 / (1024 * 1024), "KIB": 1 / 1024, "MIB": 1.0, "GIB": 1024.0,
             "KB": 1 / 1024, "MB": 1.0, "GB": 1024.0, "TIB": 1024.0 * 1024}
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
