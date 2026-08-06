# CarnoKit

CarnoKit runs and manages a four-map **ARK: Survival Ascended** cluster on
Linux. The included deployment currently hosts Aberration, Ragnarok, Genesis 1,
and Lost Colony in Docker.

It provides:

- a Discord bot for cluster status, administration, scheduled jobs, logs, and
  safe updates;
- a watchdog that recovers unresponsive servers and can restart before an
  out-of-memory failure;
- a crash analyzer for UE5 dumps and server logs; and
- deployment scripts for provisioning and maintaining the VPS.

All four maps share one transfer directory. Each map keeps its own server files,
Steam data, ports, and logs.

## Requirements

- Ubuntu 22.04 or 24.04 on x86-64
- Docker Engine with the Compose plugin
- Python 3.10 or newer
- 64 GB or more RAM
- At least 130 GB of free disk space
- A Discord bot token
- Root or sudo access during setup

## Install

Clone the repository to `/opt/asa-cluster` on the VPS:

```bash
sudo git clone https://github.com/Tristan-Duin/CarnoKit.git /opt/asa-cluster
cd /opt/asa-cluster
```

Provision the host, create the configuration files, launch the maps, and install
the management services:

```bash
sudo bash deploy/01-setup-vps.sh
cp deploy/.env.example deploy/.env
cp config.ini.example config.ini
# Edit deploy/.env and config.ini before continuing.
sudo bash deploy/02-deploy-cluster.sh
sudo bash deploy/03-setup-tooling.sh
```

Keep the shared values in `deploy/.env` and `config.ini` identical, especially
the admin password, cluster ID, mod list, and ports. Never use the example
cluster ID or password in production.

The first launch downloads a separate server installation for every map and can
take 10–30 minutes or longer per map.

See [the complete deployment guide](deploy/README.md) for configuration,
firewall rules, rates, backups, and troubleshooting.

## Routine operations

```bash
# Show the containers
docker ps

# Follow one map's startup or server log
docker logs -f asa-aberration

# Safely restart one map (warn/save first)
sudo /opt/asa-cluster/deploy/safe-shutdown.sh restart asa-aberration

# Safely stop the cluster
sudo /opt/asa-cluster/deploy/safe-shutdown.sh down
```

Use `safe-shutdown.sh` for manual stops and restarts so reachable worlds are
saved first.

The installed systemd services are:

- `asa-bot` — Discord bot, scheduler, logs, and game update orchestration
- `asa-watchdog` — RCON health and memory monitoring
- `asa-save-on-shutdown` — saves worlds when the host shuts down

View service logs with, for example:

```bash
journalctl -u asa-bot -f
journalctl -u asa-watchdog -f
```

## Discord commands

Most commands accept an optional map. If omitted, single-map commands target
the first configured map.

| Group | Common commands | Access |
| --- | --- | --- |
| Cluster | `/cluster status` | Everyone |
| Server | `/server status`, `save`, `motd`, `time`, `destroy-wild-dinos` | Mixed |
| Players | `/players list`, `message`, `broadcast`, `kick`, `ban`, `unban` | Mixed |
| Admin | `/admin give`, `xp`, `summon`, `teleport`, `set-level` | Admin/Owner |
| Scheduler | `/schedule auto-save`, `restart`, `broadcast`, `list`, `cancel` | Mixed |
| Updates | `/update check`, `status`, `now` | Mixed |
| Logs | `/logs tail`, `search` | Admin |
| Boss fights | `/boss start`, `list` | Everyone |

Set `admin_role_ids` and `owner_user_ids` under `[discord]` in `config.ini`.
The Discord server owner automatically receives Owner access. Raw RCON and the
most destructive commands are Owner-only.

## Updates and restarts

CarnoKit deliberately separates three kinds of updates:

### ARK server updates

The bot checks the public Steam build every `update_check_minutes` (15 minutes
by default). When it finds a new build, it:

1. announces a countdown in Discord and on every map;
2. sends `SaveWorld` to every map at the one-minute warning;
3. sends `SaveWorld` again immediately before shutdown;
4. waits 20 seconds for the final saves to flush; and
5. restarts all map containers together.

If any map cannot be saved, the restart is aborted. `/update now` performs this
same safe, announced cycle even when no new ARK build is available.

### Mod updates

`MODS` contains CurseForge **project IDs**, not pinned file versions. Whenever a
map container starts, ASA checks each configured project and installs its current
server release.

CarnoKit does not currently detect mod-only releases or immediately restart the
cluster for them. A mod update is therefore installed on the next manual,
scheduled, watchdog, or ARK-update restart.

To change the mod list, update `MODS` in `deploy/.env` and `mods` in
`config.ini`, then safely recreate the containers as described in the
[deployment guide](deploy/README.md#changing-mods-or-player-limit).

### CarnoKit code updates

After validation succeeds on `main`, GitHub Actions deploys that exact commit
and restarts only the bot and watchdog. It never restarts the ARK containers or
touches saves and other ignored runtime data. See
[automated deployment](docs/deployment.md) for setup and rollback behavior.

## Watchdog

The watchdog probes every map over RCON. After repeated failures it restarts the
affected container, with a per-map circuit breaker to avoid endless restart
loops. It also supports memory thresholds and gives servers a configurable boot
grace period so slow updates are not interrupted.

Managed restarts save the world whenever the server is still reachable.

## Crash analyzer

Run the analyzer on the VPS:

```bash
# Analyze all configured maps
/opt/asa-cluster/venv/bin/python /opt/asa-cluster/crash_analyzer/analyze.py

# Analyze only the latest Aberration crash
/opt/asa-cluster/venv/bin/python /opt/asa-cluster/crash_analyzer/analyze.py \
  --server aberration --last
```

Reports classify likely RCON, mod, engine, and out-of-memory failures and include
the relevant stack and log context.

## Configuration and data

- `config.ini` configures the bot, watchdog, analyzer, Discord permissions, and
  map definitions. Start from `config.ini.example`.
- `deploy/.env` configures Docker Compose. Start from `deploy/.env.example`.
- `/opt/asa-cluster/<map>/server-files/ShooterGame/Saved/` contains each map's
  saves and server configuration.
- `/opt/asa-cluster/cluster-shared/` contains cross-map transfer data.

Back up every map's `Saved/` directory and `cluster-shared/` regularly. Neither
directory is tracked by Git.

## More documentation

- [VPS deployment and server configuration](deploy/README.md)
- [Automated code deployment](docs/deployment.md)
- [Example application configuration](config.ini.example)
- [Example container configuration](deploy/.env.example)

## License

[MIT](LICENSE)
