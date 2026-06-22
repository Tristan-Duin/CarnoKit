#!/usr/bin/env bash
#
# 02-deploy-cluster.sh - Download and launch the 3-map ASA cluster.
#
# Run from the deploy directory (after editing .env):
#   bash deploy/02-deploy-cluster.sh
#
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example."
  echo "Edit deploy/.env (set ADMIN_PASSWORD etc.), then run this script again."
  exit 1
fi

# Load .env so we can pre-create the data directories.
set -a
# shellcheck disable=SC1091
source ./.env
set +a
BASE_DIR="${BASE_DIR:-/opt/asa-cluster}"

echo "==> Ensuring data directories under ${BASE_DIR}"
for srv in island scorched extinction; do
  for sub in server-files steam steamcmd; do
    mkdir -p "${BASE_DIR}/${srv}/${sub}"
  done
done
mkdir -p "${BASE_DIR}/cluster-shared"

if ! docker info >/dev/null 2>&1; then
  echo "Cannot talk to Docker. Run this as root (sudo) or add your user to the 'docker' group." >&2
  exit 1
fi

echo "==> Starting the cluster (docker compose -p asa-cluster up -d)"
docker compose -p asa-cluster up -d

cat <<EOF

Cluster is starting. The FIRST boot of each map is slow - SteamCMD downloads
the server (~10-30 GB), Proton initialises, then the mods download. Expect
10-30+ minutes before the servers advertise.

Follow progress:
  docker logs -f asa-island
  docker logs -f asa-scorched
  docker logs -f asa-extinction

Find the session name (once booted):
  docker exec asa-island cat server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini | grep SessionName

Then set up the tooling:  sudo bash 03-setup-tooling.sh
EOF
