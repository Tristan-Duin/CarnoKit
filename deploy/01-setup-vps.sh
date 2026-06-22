#!/usr/bin/env bash
#
# 01-setup-vps.sh - Prepare a fresh Ubuntu VPS to host the ASA cluster.
#
# Installs Docker + Compose, applies the mandatory kernel setting for ASA,
# adds swap, opens the game ports in the firewall, and creates the cluster
# data directories with the correct ownership.
#
# Run as root:   sudo bash deploy/01-setup-vps.sh
#
set -euo pipefail

BASE_DIR="${BASE_DIR:-/opt/asa-cluster}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-8}"
SERVER_UID=25000
SERVER_GID=25000

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root (use sudo)." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
log "Installing base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg lsb-release ufw python3 python3-venv python3-pip

# ---------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  log "Docker already installed: $(docker --version)"
else
  log "Installing Docker Engine + Compose plugin (official repository)"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker

# ---------------------------------------------------------------------------
log "Applying mandatory kernel setting (vm.max_map_count=262144)"
# Without this, ASA crashes on start with 'Allocator Stats' errors.
if ! grep -q '^vm.max_map_count' /etc/sysctl.conf 2>/dev/null; then
  echo 'vm.max_map_count=262144' >> /etc/sysctl.conf
fi
sysctl -w vm.max_map_count=262144

# ---------------------------------------------------------------------------
log "Configuring swap (${SWAP_SIZE_GB} GB)"
if swapon --show | grep -q . ; then
  warn "Swap already present; skipping."
else
  if ! fallocate -l "${SWAP_SIZE_GB}G" /swapfile 2>/dev/null; then
    dd if=/dev/zero of=/swapfile bs=1M count=$((SWAP_SIZE_GB * 1024))
  fi
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------------------------------------------------------------------------
log "Configuring firewall (ufw)"
# Allow SSH first so we don't lock ourselves out, then the game ports.
ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null 2>&1 || true
ufw allow 7777:7779/udp >/dev/null 2>&1 || true
# RCON (27020-27022) is intentionally NOT opened; it is bound to localhost.
ufw --force enable

# ---------------------------------------------------------------------------
log "Creating cluster data directories under ${BASE_DIR}"
for srv in island scorched extinction; do
  for sub in server-files steam steamcmd; do
    mkdir -p "${BASE_DIR}/${srv}/${sub}"
  done
done
mkdir -p "${BASE_DIR}/cluster-shared"

# Own ONLY the data dirs as the in-container server user (not the tooling code).
chown -R "${SERVER_UID}:${SERVER_GID}" \
  "${BASE_DIR}/island" "${BASE_DIR}/scorched" "${BASE_DIR}/extinction" "${BASE_DIR}/cluster-shared"

log "VPS setup complete."
cat <<EOF

Next steps:
  1. Put this repo at ${BASE_DIR} (so you have ${BASE_DIR}/deploy, ${BASE_DIR}/bot, ...).
  2. cd ${BASE_DIR}/deploy && cp .env.example .env  then edit .env (passwords!).
  3. bash 02-deploy-cluster.sh        # download + launch the 3 servers
  4. bash 03-setup-tooling.sh         # install + start the Discord bot + watchdog

Reminder: ensure the VPS has >=100 GB free disk (3 separate server installs).
EOF
