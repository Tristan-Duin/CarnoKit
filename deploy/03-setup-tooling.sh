#!/usr/bin/env bash
#
# 03-setup-tooling.sh - Install the Python tooling (Discord bot + watchdog)
# into a venv and run them as systemd services.
#
# Run as root:  sudo bash deploy/03-setup-tooling.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_DIR}/venv"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root (use sudo) to install systemd services." >&2
  exit 1
fi

echo "==> Creating Python virtualenv at ${VENV_DIR}"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/bot/requirements.txt"

# Sanity check: token present?
if grep -Eq '^[[:space:]]*token[[:space:]]*=[[:space:]]*$' "${REPO_DIR}/config.ini"; then
  echo "[!] config.ini has an empty Discord token - the bot will not start until you set it."
fi

echo "==> Installing systemd units (paths -> ${REPO_DIR})"
for unit in asa-bot asa-watchdog; do
  sed "s#/opt/asa-cluster#${REPO_DIR}#g" "${SCRIPT_DIR}/systemd/${unit}.service" \
    > "/etc/systemd/system/${unit}.service"
done

systemctl daemon-reload
systemctl enable asa-bot.service asa-watchdog.service
systemctl restart asa-bot.service asa-watchdog.service

cat <<EOF

Tooling installed and started.

  systemctl status asa-bot --no-pager
  systemctl status asa-watchdog --no-pager
  journalctl -u asa-bot -f          # live bot logs
  journalctl -u asa-watchdog -f     # live watchdog logs

If you change config.ini, restart the services:
  sudo systemctl restart asa-bot asa-watchdog
EOF
