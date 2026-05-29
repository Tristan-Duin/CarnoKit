from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional


@dataclass
class CrashReport:
    """Structured data extracted from one crash event."""

    crash_id: str = ""
    timestamp: Optional[datetime] = None
    crash_type: str = ""
    error_message: str = ""
    uptime_seconds: int = 0
    engine_version: str = ""
    build_version: str = ""

    # Call stack
    call_stack: List[str] = field(default_factory=list)
    top_function: str = ""
    faulting_module: str = ""

    # Memory
    total_physical_gb: int = 0
    is_oom: bool = False

    # Analysis
    category: str = ""          # "rcon", "mod", "engine", "oom", "unknown"
    blame: str = ""             # Human-readable cause
    mod_name: str = ""          # If a mod DLL is in the stack
    rcon_command: str = ""      # If RCON triggered it
    actionable: str = ""        # What the admin can do

    # Source paths
    crash_dir: str = ""
    crashstack_file: str = ""

    # Pre-crash log lines
    log_context: List[str] = field(default_factory=list)


def parse_crash_context(xml_path: Path) -> CrashReport:
    """Parse a CrashContext.runtime-xml file into a CrashReport."""
    report = CrashReport()
    report.crash_dir = str(xml_path.parent)

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        props = root.find("RuntimeProperties")
        if props is None:
            return report

        report.crash_id = _text(props, "CrashGUID")
        report.crash_type = _text(props, "CrashType")
        report.error_message = _text(props, "ErrorMessage")
        report.engine_version = _text(props, "EngineVersion")
        report.build_version = _text(props, "BuildVersion")

        uptime_str = _text(props, "SecondsSinceStart")
        report.uptime_seconds = int(uptime_str) if uptime_str.isdigit() else 0

        total_gb_str = _text(props, "MemoryStats.TotalPhysicalGB")
        report.total_physical_gb = int(total_gb_str) if total_gb_str.isdigit() else 0
        report.is_oom = _text(props, "MemoryStats.bIsOOM") == "1"

        # Parse the symbolic call stack
        raw_stack = _text(props, "CallStack")
        if raw_stack:
            report.call_stack = [
                line.strip() for line in raw_stack.strip().splitlines() if line.strip()
            ]
            if report.call_stack:
                report.top_function = _extract_function_name(report.call_stack[0])

        # File timestamp
        try:
            report.timestamp = datetime.fromtimestamp(xml_path.stat().st_mtime)
        except Exception:
            pass

    except ET.ParseError:
        pass

    _analyze(report)
    return report


def parse_crashstack(path: Path) -> CrashReport:
    """Parse a .crashstack file (UTF-16LE) into a CrashReport."""
    report = CrashReport()
    report.crashstack_file = str(path)

    try:
        text = path.read_text(encoding="utf-16-le", errors="replace")
    except Exception:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return report

    lines = text.strip().splitlines()
    if not lines:
        return report

    # First non-empty line is usually "Fatal error!"
    # Error message is usually line 3
    for line in lines:
        line = line.strip()
        if line.startswith("Unhandled Exception") or line.startswith("EXCEPTION"):
            report.error_message = line
            break
        if "Fatal error" in line:
            continue
        if line.startswith("CL:"):
            continue

    # Stack frames start with "0x" addresses
    stack = []
    for line in lines:
        line = line.strip()
        if line.startswith("0x") and "!" in line:
            # Extract the symbolic part: "ArkAscendedServer.exe!Function() [file:line]"
            m = re.match(r"0x[0-9a-f]+ (.+)", line)
            if m:
                stack.append(m.group(1).strip())
    report.call_stack = stack
    if stack:
        report.top_function = _extract_function_name(stack[0])

    # Timestamp from filename: "05.27-21.56.57.crashstack"
    m = re.search(r"(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2})", path.name)
    if m:
        try:
            now = datetime.now()
            report.timestamp = datetime(
                now.year, int(m.group(1)), int(m.group(2)),
                int(m.group(3)), int(m.group(4)), int(m.group(5))
            )
        except ValueError:
            pass

    _analyze(report)
    return report


def parse_server_log_tail(log_path: Path, before_time: Optional[datetime] = None,
                          n_lines: int = 50) -> List[str]:
    """Read the last N lines from a server log, optionally filtering to lines before a timestamp."""
    if not log_path.exists():
        return []

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    lines = text.strip().splitlines()
    if before_time is None:
        return lines[-n_lines:]

    # Filter lines with timestamps before the crash
    result = []
    for line in lines:
        m = re.match(r"\[(\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2})", line)
        if m:
            try:
                ts = datetime.strptime(m.group(1), "%Y.%m.%d-%H.%M.%S")
                if ts <= before_time:
                    result.append(line)
            except ValueError:
                result.append(line)
        else:
            result.append(line)

    return result[-n_lines:]


def find_log_for_crash(logs_dir: Path, crash_time: Optional[datetime]) -> Optional[Path]:
    """Find the server log file that was active during a crash."""
    if not logs_dir.exists():
        return None

    # Get all ShooterGame log files sorted by modification time
    logs = sorted(logs_dir.glob("ShooterGame*.log"), key=lambda p: p.stat().st_mtime)

    if crash_time is None:
        return logs[-1] if logs else None

    # Find the log whose modification time is closest to (and after) the crash
    for log_file in reversed(logs):
        try:
            mod_time = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mod_time >= crash_time - timedelta(minutes=5):
                return log_file
        except Exception:
            continue

    return logs[-1] if logs else None


_KNOWN_RCON_FUNCTIONS = {
    "RCONClientConnection::ProcessRCONPacket",
    "RCONClientConnection::Tick",
    "URCONServer::Tick",
}

_CHEAT_FUNCTIONS = {
    "UCheatManager::Fly": "Fly",
    "UCheatManager::God": "God",
    "UCheatManager::Slomo": "Slomo",
    "UCheatManager::Ghost": "Ghost",
    "UCheatManager::Walk": "Walk",
    "UCheatManager::Teleport": "Teleport",
    "UCheatManager::ChangeSize": "ChangeSize",
    "UCheatManager::ProcessConsoleExec": "console command",
}

# Known engine modules (not mods)
_ENGINE_MODULES = {
    "ArkAscendedServer", "ArkAscendedServer.exe",
    "kernel32", "ntdll", "KERNELBASE",
    "VCRUNTIME140", "ucrtbase", "msvcp140",
}


def _analyze(report: CrashReport) -> None:
    """Categorize the crash and determine blame."""
    stack_text = "\n".join(report.call_stack)

    # Check for RCON-triggered crashes
    is_rcon = any(
        func in stack_text for func in _KNOWN_RCON_FUNCTIONS
    )

    # Check for specific cheat command
    cheat_cmd = ""
    for func_name, cmd in _CHEAT_FUNCTIONS.items():
        if func_name in stack_text:
            cheat_cmd = cmd
            break

    # Check for mod DLLs in the stack
    mod_modules = set()
    for frame in report.call_stack:
        module = _extract_module(frame)
        if module and module not in _ENGINE_MODULES:
            mod_modules.add(module)

    # Check for OOM
    if report.is_oom or "out of memory" in report.error_message.lower():
        report.category = "oom"
        report.blame = "Server ran out of memory"
        report.actionable = (
            "Increase system RAM, reduce mod count, or set up periodic "
            "restarts to clear memory leaks before they accumulate."
        )
        return

    # RCON-triggered crash
    if is_rcon:
        report.category = "rcon"
        if cheat_cmd:
            report.rcon_command = cheat_cmd
            report.blame = (
                f"RCON cheat command '{cheat_cmd}' crashed the server. "
                f"This command requires a player context that doesn't exist in RCON."
            )
            report.actionable = (
                f"Remove or disable the '{cheat_cmd}' command from RCON usage. "
                f"These cheat commands only work from an in-game admin console, not remotely."
            )
        else:
            report.blame = "An RCON command triggered a crash in the server."
            report.actionable = (
                "Check your RCON bot commands. Some cheat commands crash the server "
                "when sent without a player context."
            )
        return

    # Mod-caused crash
    if mod_modules:
        report.category = "mod"
        report.mod_name = ", ".join(sorted(mod_modules))
        report.blame = f"Crash in mod module(s): {report.mod_name}"
        report.faulting_module = list(mod_modules)[0]
        report.actionable = (
            f"The mod '{report.mod_name}' is likely causing this crash. "
            f"Check for mod updates, or try disabling it to confirm."
        )
        return

    # Generic engine crash
    report.category = "engine"
    if report.top_function:
        report.blame = f"Engine crash in {report.top_function}"
    else:
        report.blame = "Unreal Engine crash (no symbolic info)"

    if "access_violation" in report.error_message.lower():
        addr = re.search(r"address (0x[0-9a-f]+)", report.error_message, re.I)
        if addr and int(addr.group(1), 16) < 0x10000:
            report.blame += " — null pointer dereference"
            report.actionable = (
                "This is a null pointer crash in the game engine. Usually caused by "
                "a game bug or an edge case the developers didn't handle. "
                "Check for game updates, validate server files, or report to the developers."
            )
        else:
            report.actionable = (
                "Access violation in game code. Validate server files with SteamCMD, "
                "check for game updates, and review recent config changes."
            )
    else:
        report.actionable = "Check for game updates and validate server files."


def _text(parent: ET.Element, tag: str) -> str:
    """Get text content of a child element, or empty string."""
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _extract_function_name(frame: str) -> str:
    """Extract just the function name from a call stack frame."""
    # "ArkAscendedServer!UCheatManager::Fly() [file:line]"
    m = re.search(r"!(.+?)(?:\s*\[|$)", frame)
    if m:
        return m.group(1).strip().rstrip("()")
    # "ArkAscendedServer.exe!UCheatManager::Fly() [file:line]"
    m = re.search(r"\.exe!(.+?)(?:\s*\[|$)", frame)
    if m:
        return m.group(1).strip().rstrip("()")
    return frame.split("!")[1].strip() if "!" in frame else frame


def _extract_module(frame: str) -> str:
    """Extract the module name from a call stack frame."""
    # "ArkAscendedServer!Function..."
    m = re.match(r"(\S+?)(?:\.exe)?!", frame)
    if m:
        return m.group(1)
    # "ModName 0x00007ff..."
    m = re.match(r"(\S+)\s+0x", frame)
    if m:
        return m.group(1)
    return ""
