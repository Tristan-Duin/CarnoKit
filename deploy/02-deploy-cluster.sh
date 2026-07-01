#!/usr/bin/env bash
#
# 02-deploy-cluster.sh - Download and launch the 4-map ASA cluster.
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
SERVER_UID=25000
SERVER_GID=25000

echo "==> Ensuring data directories under ${BASE_DIR}"
for srv in island scorched valguero lostcolony; do
  for sub in server-files steam steamcmd; do
    mkdir -p "${BASE_DIR}/${srv}/${sub}"
  done
  mkdir -p "${BASE_DIR}/${srv}/steam/compatibilitytools.d"
done
mkdir -p "${BASE_DIR}/cluster-shared"

if [[ "${EUID}" -eq 0 ]]; then
  echo "==> Fixing data directory ownership for the in-container gameserver user"
  chown -R "${SERVER_UID}:${SERVER_GID}" \
    "${BASE_DIR}/island" \
    "${BASE_DIR}/scorched" \
    "${BASE_DIR}/valguero" \
    "${BASE_DIR}/lostcolony" \
    "${BASE_DIR}/cluster-shared"
else
  echo "==> Not running as root; skipping ownership repair."
  echo "    If containers log Permission denied, run this script with sudo."
fi

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
  docker logs -f asa-valguero
  docker logs -f asa-lostcolony

Find the session name (once booted):
  docker exec asa-island cat server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini | grep SessionName

Then set up the tooling:  sudo bash 03-setup-tooling.sh
EOF
