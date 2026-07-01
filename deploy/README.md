# ARK: Survival Ascended - 4-Map Cluster on a VPS

This repo deploys a clustered **ARK: Survival Ascended** server (The Island,
Scorched Earth, Valguero, Lost Colony) on an Ubuntu VPS using Docker, with the
Discord bot, watchdog, crash analyzer, and auto-updater tooling.

The ASA dedicated server is Windows-only; on Linux it runs inside the
maintained `mschnitzer/asa-linux-server` image via Proton.

## What you get
- 4 clustered maps sharing characters/dinos (one `cluster-shared` volume).
- Mods on every map: Cybers Structures QoL+ (`940975`), Configurable
  Cryopods (`929169`)
- A Discord bot to manage every map (`/cluster status`, `/server`, `/players`,
  `/admin`, `/logs`, `/schedule`, `/update`).
- A watchdog that restarts an unresponsive container automatically.
- A crash analyzer and a SteamCMD-based auto-updater.

## Requirements
- Ubuntu 24.04 LTS (22.04 also works) x86_64 VPS.
- **64 GB+ RAM** (each map uses ~13 GB).
- **>= 100 GB free disk** (each map is a separate ~30 GB install).
- Root/sudo access.

## Layout (on the VPS)
Put this repo at `/opt/asa-cluster` so you have:
```
/opt/asa-cluster/
  config.ini            # shared tooling config (token, passwords, servers)
  bot/  watchdog/  crash_analyzer/
  deploy/               # the scripts below + docker-compose.yml + .env
  venv/                 # created by 03-setup-tooling.sh
  island/  scorched/  valguero/  lostcolony/  # per-map data
  cluster-shared/       # cross-map transfers
```
> The default base directory is `/opt/asa-cluster`. If you deploy elsewhere,
> update `base_dir` in `config.ini` and `BASE_DIR` in `deploy/.env`; the
> tooling setup script auto-adjusts the systemd unit paths.

## Deploy, step by step
1. **Upload the repo** to the VPS at `/opt/asa-cluster` (scp/rsync/git).
   Ensure the shell scripts use Unix (LF) line endings - if you edited them on
   Windows, run `sudo apt-get install -y dos2unix && dos2unix deploy/*.sh`.
2. **Provision the VPS** (Docker, kernel setting, swap, firewall, dirs):
   ```bash
   sudo bash /opt/asa-cluster/deploy/01-setup-vps.sh
   ```
3. **Configure secrets** (keep these two files in sync):
   - `deploy/.env` (copied from `.env.example`): `ADMIN_PASSWORD`, optional
     `JOIN_PASSWORD`, `CLUSTER_ID`, `MODS`, ports.
   - `config.ini`: `[discord] token`, and the matching `[cluster]`
     `admin_password`, `join_password`, `cluster_id`, `mods`.
   ```bash
   cd /opt/asa-cluster/deploy
   cp .env.example .env
   nano .env            # set ADMIN_PASSWORD etc.
   nano ../config.ini   # set the Discord token + matching admin_password
   ```
4. **Launch the cluster**:
   ```bash
   sudo bash /opt/asa-cluster/deploy/02-deploy-cluster.sh
   ```
   First boot is slow (SteamCMD download + Proton + mod download): 10-30+ min
   per map. Watch with `docker logs -f asa-island`.
5. **Install the tooling** (bot + watchdog as systemd services):
   ```bash
   sudo bash /opt/asa-cluster/deploy/03-setup-tooling.sh
   ```

## Ports
| Map           | Game (UDP) | RCON (TCP, localhost only) |
| ------------- | ---------- | -------------------------- |
| The Island    | 7777       | 27020                      |
| Scorched Earth| 7778       | 27021                      |
| Valguero      | 7779       | 27022                      |
| Lost Colony   | 7780       | 27023                      |

Only the game UDP ports are opened to the internet (by `01-setup-vps.sh`).
RCON is published on `127.0.0.1` only and used by the local tooling. ASA has
no separate query port.

## Managing the cluster
```bash
# Status / logs
docker ps
docker logs -f asa-island

# Stop / start / restart one map or all
docker compose -p asa-cluster restart asa-island
cd /opt/asa-cluster/deploy && docker compose -p asa-cluster down
cd /opt/asa-cluster/deploy && docker compose -p asa-cluster up -d

# Game/server config files (per map), editable on the host:
#   /opt/asa-cluster/<map>/server-files/ShooterGame/Saved/Config/WindowsServer/
#   GameUserSettings.ini and Game.ini  (restart the container after editing)
```

### Changing mods or player limit
Edit `MODS` / `MAX_PLAYERS` in `deploy/.env` (and mirror `mods` in
`config.ini`), then recreate the containers:
```bash
cd /opt/asa-cluster/deploy && docker compose -p asa-cluster up -d --force-recreate
```

## The tooling
All tooling reads `/opt/asa-cluster/config.ini`. Commands accept an optional
`server` argument that defaults to the first configured map.
- **Bot**: `systemctl status asa-bot`, logs via `journalctl -u asa-bot -f`.
  Key commands: `/cluster status`, `/server status|save|motd|time|raw`,
  `/players ...`, `/admin ...`,
  `/logs tail|search`, `/schedule restart|broadcast|auto-save`,
  `/update check|status|now`.
- **Watchdog**: probes each map's RCON; after repeated failures it runs
  `docker restart` on that container (per-map circuit breaker + boot grace so
  first boots/updates aren't interrupted). `journalctl -u asa-watchdog -f`.
- **Auto-updater** (inside the bot): checks the latest Steam build via a
  throwaway `steamcmd` container; on a new build it warns in-game, saves, and
  `docker restart`s each map (the image self-updates on start).
- **Crash analyzer** (run on demand):
  ```bash
  /opt/asa-cluster/venv/bin/python /opt/asa-cluster/crash_analyzer/analyze.py            # all maps
  /opt/asa-cluster/venv/bin/python /opt/asa-cluster/crash_analyzer/analyze.py --server island --last
  ```

## Keeping config.ini and .env in sync
`config.ini` drives the tooling; `deploy/.env` drives the containers. The
shared values (`admin_password`/`ADMIN_PASSWORD`, `join_password`/
`JOIN_PASSWORD`, `cluster_id`/`CLUSTER_ID`, `mods`/`MODS`, and the ports) must
match. If RCON auth fails in the bot/watchdog, the passwords are out of sync.

## Notes
- `vm.max_map_count=262144` is mandatory and is set by `01-setup-vps.sh`
  (persisted in `/etc/sysctl.conf`). Without it ASA crashes on start.
- Back up each map's save directory:
  `/opt/asa-cluster/<map>/server-files/ShooterGame/Saved/`.
- The bot/watchdog run as root so they can call `docker`. To run them as a
  non-root user, add that user to the `docker` group and set `User=` in the
  systemd units.

## Server rates & mod configuration
`deploy/04-apply-rates.sh` applies the gameplay configuration to every map and
restarts the cluster. The shipped profile is **PvE, ~3-5x rates, moderate
breeding, official wild level 150**, plus QoL and the mod settings:
- Rates: XP 3x, Harvest 3x, Taming 5x, faster resource respawn, 5x item stacks.
- Breeding: ~15x maturation, 10x hatch, lower cuddle interval, slower baby food drain.
- PvE: structure/dino decay off, flyer carry, cave building, cluster transfers enabled.
- Mods: Configurable Cryopods tuned (no cryo sickness, cryo rifle, etc.) and
  Cybers Structures `EnableEngramOverride=True` (vanilla building engrams are
  replaced by the CS versions so you don't get duplicates).
- Server-list names: each map advertises as `Battling Poverty [Island]`,
  `Battling Poverty [Scorched]`, `Battling Poverty [Valguero]`, and
  `Battling Poverty [Lost Colony]` (the prefix is `CLUSTER_NAME` in the script).
Run it (idempotent - edit the values in the script and re-run anytime):
```bash
sudo bash /opt/asa-cluster/deploy/04-apply-rates.sh
```
It backs up each map's `Game.ini`/`GameUserSettings.ini` first, then merges in
place (it sets each map's `SessionName` from `CLUSTER_NAME`; your
`ServerAdminPassword` and other keys are preserved). After it restarts
the cluster, wipe wild dinos once (`/server destroy-wild-dinos` per map, or RCON
`DestroyWildDinos`) so the difficulty and Shad's Critter Reworks variants spawn.
For a join password, set `ServerPassword` in each map's `GameUserSettings.ini`
(never on the command line - a space there corrupts the admin password).
## Troubleshooting
- **Server won't appear / start**: `docker logs asa-island`; confirm
  `vm.max_map_count` (`sysctl vm.max_map_count`) and that game UDP ports are
  open at the VPS firewall *and* provider security group.
- **Bot/watchdog can't reach RCON**: confirm the container is past first boot,
  and that `admin_password` (config.ini) == `ADMIN_PASSWORD` (.env).
- **Out of disk**: 3 installs are large; check `df -h`.
