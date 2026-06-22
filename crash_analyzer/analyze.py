"""
ARK Survival Ascended - Crash Analyzer (cluster-aware)

Scans crash dumps, crashstack files, and server logs for one or every
server in the cluster and produces a human-readable report explaining what
crashed, why, and what to do about it.

Usage:
    py analyze.py                         # Analyze every server in config.ini
    py analyze.py --server island         # Analyze just one map
    py analyze.py --last                   # Only the most recent crash (per server)
    py analyze.py --json                   # Output as JSON
    py analyze.py --server-dir /path/sf    # Analyze one explicit server-files dir
"""

from __future__ import annotations

import argparse
import configparser
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from parser import (
    CrashReport,
    find_log_for_crash,
    parse_crash_context,
    parse_crashstack,
    parse_server_log_tail,
)

# Default paths
_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.ini"
CRASHES_REL = Path("ShooterGame/Saved/Crashes")
LOGS_REL = Path("ShooterGame/Saved/Logs")


def _read_servers(config_path: Path) -> Dict[str, Tuple[str, Path]]:
    """Return {key: (display_name, server_files_dir)} from the cluster config."""
    cp = configparser.ConfigParser()
    cp.read(config_path, encoding="utf-8")
    base = cp.get("cluster", "base_dir", fallback="/opt/asa-cluster")
    servers: Dict[str, Tuple[str, Path]] = {}
    raw = cp.get("servers", "list", fallback="")
    for key in [k.strip() for k in raw.split(",") if k.strip()]:
        section = f"server.{key}"
        if not cp.has_section(section):
            continue
        name = cp.get(section, "name", fallback=key)
        log_file = cp.get(section, "log_file", fallback="")
        if log_file:
            # <server-files>/ShooterGame/Saved/Logs/ShooterGame.log -> <server-files>
            server_dir = Path(log_file).parents[3]
        else:
            server_dir = Path(base) / key / "server-files"
        servers[key] = (name, server_dir)
    return servers


def collect_crashes(server_dir: Path) -> List[CrashReport]:
    """Find and parse all crash data from a server-files directory."""
    reports: List[CrashReport] = []
    seen_ids: set[str] = set()

    crashes_dir = server_dir / CRASHES_REL
    logs_dir = server_dir / LOGS_REL

    # 1. Parse CrashContext.runtime-xml files (richest data)
    if crashes_dir.exists():
        for xml_file in crashes_dir.rglob("CrashContext.runtime-xml"):
            report = parse_crash_context(xml_file)
            if report.crash_id:
                seen_ids.add(report.crash_id)
            log_file = find_log_for_crash(logs_dir, report.timestamp)
            if log_file:
                report.log_context = parse_server_log_tail(
                    log_file, before_time=report.timestamp, n_lines=30
                )
            reports.append(report)

    # 2. Parse .crashstack files (may cover crashes without XML dumps)
    if logs_dir.exists():
        for cs_file in logs_dir.glob("*.crashstack"):
            report = parse_crashstack(cs_file)
            if report.crash_id and report.crash_id in seen_ids:
                continue
            if report.timestamp and any(
                r.timestamp and abs((r.timestamp - report.timestamp).total_seconds()) < 60
                for r in reports
            ):
                for r in reports:
                    if r.timestamp and abs((r.timestamp - report.timestamp).total_seconds()) < 60:
                        if not r.call_stack and report.call_stack:
                            r.call_stack = report.call_stack
                            r.top_function = report.top_function
                        r.crashstack_file = report.crashstack_file
                        break
                continue
            reports.append(report)

    reports.sort(key=lambda r: r.timestamp or datetime.min, reverse=True)
    return reports


def format_uptime(seconds: int) -> str:
    """Format uptime seconds into a readable string."""
    if seconds <= 0:
        return "unknown"
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(int(td.total_seconds()), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_report(reports: List[CrashReport], *, verbose: bool = True) -> str:
    """Format crash reports into a human-readable string."""
    if not reports:
        return "No crashes found. Server appears stable."

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("  ARK SURVIVAL ASCENDED - CRASH ANALYSIS REPORT")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Total crashes found: {len(reports)}")
    lines.append("=" * 72)

    # Summary statistics
    categories = {}
    for r in reports:
        cat = r.category or "unknown"
        categories[cat] = categories.get(cat, 0) + 1

    lines.append("")
    lines.append("CRASH SUMMARY")
    lines.append("-" * 40)
    cat_labels = {
        "rcon": "RCON/Bot-caused",
        "mod": "Mod-caused",
        "engine": "Engine/Game bug",
        "oom": "Out of Memory",
        "unknown": "Unknown",
    }
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        label = cat_labels.get(cat, cat)
        lines.append(f"  {label}: {count}")

    # Uptime analysis
    uptimes = [r.uptime_seconds for r in reports if r.uptime_seconds > 0]
    if uptimes:
        avg_uptime = sum(uptimes) / len(uptimes)
        min_uptime = min(uptimes)
        max_uptime = max(uptimes)
        lines.append("")
        lines.append("UPTIME AT CRASH")
        lines.append("-" * 40)
        lines.append(f"  Average: {format_uptime(int(avg_uptime))}")
        lines.append(f"  Shortest: {format_uptime(min_uptime)}")
        lines.append(f"  Longest:  {format_uptime(max_uptime)}")
        if avg_uptime < 3600:
            lines.append("  [!] Average uptime is under 1 hour -- likely a recurring bug.")
        elif avg_uptime < 14400:
            lines.append("  [!] Average uptime is under 4 hours -- possible memory leak.")

    # Detailed crash reports
    lines.append("")
    lines.append("=" * 72)
    lines.append("DETAILED CRASH REPORTS")
    lines.append("=" * 72)

    for i, report in enumerate(reports, 1):
        lines.append("")
        lines.append(f"--- Crash #{i} ---------------------------------------------")
        ts = report.timestamp.strftime("%Y-%m-%d %H:%M:%S") if report.timestamp else "unknown"
        lines.append(f"  Time:     {ts}")
        lines.append(f"  Uptime:   {format_uptime(report.uptime_seconds)}")
        lines.append(f"  Type:     {report.crash_type or 'Crash'}")
        lines.append(f"  Error:    {report.error_message or 'unknown'}")
        lines.append(f"  Build:    {report.build_version or report.engine_version or 'unknown'}")

        if report.category:
            lines.append(f"  Category: {report.category.upper()}")

        lines.append("")
        lines.append(f"  CAUSE: {report.blame}")
        lines.append(f"  FIX:   {report.actionable}")

        if verbose and report.call_stack:
            lines.append("")
            lines.append("  CALL STACK (top 8 frames):")
            for frame in report.call_stack[:8]:
                frame = frame.replace("ArkAscendedServer!", "")
                frame = frame.replace("ArkAscendedServer.exe!", "")
                frame = frame.replace("C:\\j\\workspace\\RelB\\", "")
                lines.append(f"    -> {frame}")

        if verbose and report.log_context:
            lines.append("")
            lines.append("  SERVER LOG (last lines before crash):")
            for log_line in report.log_context[-10:]:
                lines.append(f"    {log_line[:120]}")

    # Recommendations
    lines.append("")
    lines.append("=" * 72)
    lines.append("RECOMMENDATIONS")
    lines.append("=" * 72)

    rcon_crashes = categories.get("rcon", 0)
    mod_crashes = categories.get("mod", 0)
    engine_crashes = categories.get("engine", 0)
    oom_crashes = categories.get("oom", 0)

    recs = []
    if rcon_crashes > 0:
        recs.append(
            f"  1. {rcon_crashes} crash(es) were caused by RCON bot commands. "
            f"Review which cheat commands your bot sends - commands like Fly, God, "
            f"and Slomo crash the dedicated server because they need a player context "
            f"that doesn't exist in RCON."
        )
    if mod_crashes > 0:
        mod_names = set(r.mod_name for r in reports if r.mod_name)
        recs.append(
            f"  {'2' if recs else '1'}. {mod_crashes} crash(es) were caused by mods: "
            f"{', '.join(mod_names)}. Check for updates to these mods, or test "
            f"the server without them to confirm stability."
        )
    if oom_crashes > 0:
        recs.append(
            f"  {len(recs)+1}. {oom_crashes} crash(es) from out-of-memory. "
            f"Set up scheduled restarts every 4-6 hours to clear memory leaks, "
            f"or enable the watchdog memory limit to restart before a hard crash."
        )
    if engine_crashes > 0:
        recs.append(
            f"  {len(recs)+1}. {engine_crashes} crash(es) in the game engine itself. "
            f"Restart the container to re-validate files via SteamCMD, "
            f"and check if a game update is available."
        )
    if uptimes and sum(uptimes) / len(uptimes) < 14400:
        recs.append(
            f"  {len(recs)+1}. Average uptime is short - the watchdog will auto-restart "
            f"crashed containers; consider scheduled restarts to pre-empt memory issues."
        )

    if recs:
        lines.append("")
        for rec in recs:
            lines.append(rec)
            lines.append("")
    else:
        lines.append("")
        lines.append("  No specific recommendations - server appears stable.")

    lines.append("=" * 72)
    return "\n".join(lines)


def reports_to_json(reports: List[CrashReport]) -> str:
    """Serialize crash reports to JSON."""
    data = []
    for r in reports:
        data.append({
            "crash_id": r.crash_id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "crash_type": r.crash_type,
            "error_message": r.error_message,
            "uptime_seconds": r.uptime_seconds,
            "uptime_human": format_uptime(r.uptime_seconds),
            "engine_version": r.engine_version,
            "build_version": r.build_version,
            "category": r.category,
            "blame": r.blame,
            "actionable": r.actionable,
            "mod_name": r.mod_name,
            "rcon_command": r.rcon_command,
            "top_function": r.top_function,
            "is_oom": r.is_oom,
            "call_stack_top5": r.call_stack[:5],
        })
    return json.dumps(data, indent=2)


def _resolve_targets(args) -> List[Tuple[str, Path]]:
    """Build the list of (label, server_dir) to analyze."""
    if args.server_dir:
        return [("custom", args.server_dir)]

    servers = _read_servers(args.config)
    if not servers:
        print("No servers configured in config.ini ([servers] list).", file=sys.stderr)
        sys.exit(1)

    if args.server:
        if args.server not in servers:
            print(
                f"Unknown server '{args.server}'. Known: {', '.join(servers)}",
                file=sys.stderr,
            )
            sys.exit(1)
        name, d = servers[args.server]
        return [(name, d)]

    return [(name, d) for (name, d) in servers.values()]


def main():
    ap = argparse.ArgumentParser(description="ARK Survival Ascended Crash Analyzer")
    ap.add_argument("--config", type=Path, default=_DEFAULT_CONFIG,
                     help="Path to shared config.ini (default: ../config.ini)")
    ap.add_argument("--server", default=None,
                     help="Server key to analyze (e.g. island). Default: all servers")
    ap.add_argument("--server-dir", type=Path, default=None,
                     help="Analyze one explicit server-files directory (overrides --server)")
    ap.add_argument("--last", action="store_true",
                     help="Only analyze the most recent crash (per server)")
    ap.add_argument("--json", action="store_true",
                     help="Output as JSON instead of text report")
    ap.add_argument("--brief", action="store_true",
                     help="Shorter report without call stacks and logs")
    args = ap.parse_args()

    targets = _resolve_targets(args)

    if args.json:
        out: Dict[str, list] = {}
        for label, server_dir in targets:
            reports = collect_crashes(server_dir) if server_dir.exists() else []
            if args.last and reports:
                reports = [reports[0]]
            out[label] = json.loads(reports_to_json(reports))
        print(json.dumps(out, indent=2))
        return

    blocks: List[str] = []
    for label, server_dir in targets:
        header = f"\n##### SERVER: {label}  ({server_dir}) #####"
        if not server_dir.exists():
            blocks.append(header + "\n  (server-files directory not found - server not installed yet?)\n")
            continue
        reports = collect_crashes(server_dir)
        if args.last and reports:
            reports = [reports[0]]
        blocks.append(header + "\n" + format_report(reports, verbose=not args.brief))

    print("\n".join(blocks))


if __name__ == "__main__":
    main()
