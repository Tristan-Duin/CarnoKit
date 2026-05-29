# CarnoKit

Server management toolkit. Three standalone tools, one config file.

| Tool | What it does |
|---|---|
| **Bot** | Discord bot - RCON commands, player management, auto-updates, scheduled restarts, server logs |
| **Watchdog** | Keeps the server alive - auto-restarts on crash, memory monitoring, circuit breaker |
| **Crash Analyzer** | Parses UE5 crash dumps, identifies the cause, tells you how to fix it |

## Requirements

- Python 3.10+
- Dedicated Server with RCON enabled
- Discord bot token (for the bot only)

## Get er' Runnin

```
git clone https://github.com/Tristan-Duin/CarnoKit.git
cd CarnoKit
pip install .[all]
copy config.example.ini config.ini
```

Edit `config.ini` with your server paths, RCON password, and Discord bot token.

Then run whichever tools you want:

```
python bot/main.py                # Discord bot
python watchdog/watchdog.py       # Process watchdog
python crash_analyzer/analyze.py  # Crash report
```

## Install Options

Install only what you want:

```
pip install .[bot]          # Discord bot only
pip install .[watchdog]     # Watchdog only
pip install .[all]          # Everything
```

The crash analyzer needs no install - it uses Python stdlib only.

## Configuration

All settings live in `config.ini` at the project root. Each tool reads only the sections it needs.

| Section | Used by | Required fields |
|---|---|---|
| `[server]` | All three | `dir` |
| `[rcon]` | Bot, Watchdog | `password` |
| `[discord]` | Bot | `token` |
| `[steamcmd]` | Bot | `path` |
| `[scheduler]` | Bot | (all optional) |
| `[watchdog]` | Watchdog | (all optional) |

See `config.example.ini` for all available settings with descriptions.

## Bot Commands

### Server
| Command | Description | Permission |
|---|---|---|
| `/server status` | Server status and online players | Everyone |
| `/server save` | Force world save | Admin |
| `/server destroy-wild-dinos` | Wipe wild dinos (confirms first) | Admin |
| `/server motd [message]` | Get or set Message of the Day | Admin |
| `/server time <HH:MM>` | Set in-game time | Admin |
| `/server raw <command>` | Run any RCON command | Owner |

### Players
| Command | Description | Permission |
|---|---|---|
| `/players list` | Show online players with IDs | Everyone |
| `/players kick <player> [reason]` | Kick a player | Admin |
| `/players ban <player> [reason]` | Ban a player | Admin |
| `/players unban <id>` | Unban a player | Admin |
| `/players message <player> <text>` | DM a player in-game | Mod |
| `/players broadcast <text>` | Server-wide broadcast | Mod |

### Admin
| Command | Description | Permission |
|---|---|---|
| `/admin give <player> <item> [qty] [quality]` | Give items to a player | Admin |
| `/admin xp <player> <amount>` | Give XP to a player | Admin |
| `/admin summon <creature>` | Spawn a creature | Admin |
| `/admin teleport <player>` | Teleport a player to you | Admin |
| `/admin set-level <player> <level>` | Set a player's level | Admin |
| `/admin rename-tribe <name> <new_name>` | Rename a tribe | Admin |
| `/admin kill <player>` | Kill a player | Owner |
| `/admin clear-inventory <player>` | Clear a player's inventory | Owner |
| `/admin destroy-tame` | Destroy targeted tame (in-game) | Owner |
| `/admin pvp-toggle` | Toggle global PvP | Owner |

### Scheduler
| Command | Description | Permission |
|---|---|---|
| `/schedule auto-save <minutes>` | Set auto-save interval (0 = off) | Admin |
| `/schedule restart <cron>` | Schedule recurring restarts | Admin |
| `/schedule broadcast <cron> <msg>` | Schedule recurring broadcasts | Admin |
| `/schedule list` | Show active schedules | Everyone |
| `/schedule cancel <id>` | Cancel a schedule | Admin |

### Updates
| Command | Description | Permission |
|---|---|---|
| `/update check` | Check for server updates | Admin |
| `/update status` | Show installed vs latest build | Everyone |
| `/update now` | Force update with countdown | Owner |

### Logs
| Command | Description | Permission |
|---|---|---|
| `/logs tail [lines]` | Show last N log lines | Mod |
| `/logs search <query>` | Search server logs | Mod |

## Watchdog

Monitors `ArkAscendedServer.exe` and keeps it running:

- **Crash recovery** - detects process death, auto-restarts within seconds
- **Circuit breaker** - stops restarting after 3 crashes in 10 minutes (configurable)
- **Memory monitor** - graceful restart with player warnings before OOM crashes
- **RCON warnings** - countdown broadcasts in-game before any restart

```
python watchdog/watchdog.py             # Normal operation
python watchdog/watchdog.py --dry-run   # Monitor only, no restarts
```

## Crash Analyzer

Scans `ShooterGame/Saved/Crashes/` and server logs. Classifies each crash:

| Category | Meaning |
|---|---|
| **RCON** | An RCON command crashed the server |
| **Mod** | A mod DLL appears in the crash stack |
| **Engine** | Game bug (null pointer, access violation) |
| **OOM** | Server ran out of memory |

Each crash report includes the cause, the fix, the call stack, and the server log lines leading up to the crash.

```
python crash_analyzer/analyze.py           # Full report
python crash_analyzer/analyze.py --last    # Most recent crash only
python crash_analyzer/analyze.py --brief   # Summary without stacks
python crash_analyzer/analyze.py --json    # Machine-readable output
```

## Permissions

Set Discord role/user IDs in `config.ini` under `[discord]`:

| Tier | Access | Config key |
|---|---|---|
| **Owner** | All commands including raw RCON | `owner_user_ids` |
| **Admin** | Server management, kicks, bans, admin cheats | `admin_role_ids` |
| **Mod** | Broadcasts, messaging, log viewing | `mod_role_ids` |

The Discord server owner automatically gets Owner tier.
