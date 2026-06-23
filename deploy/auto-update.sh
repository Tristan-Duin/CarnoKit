#!/usr/bin/env bash
#
# auto-update.sh - Pull the latest code from origin/main and restart the ARK
# tooling services. Installed to /usr/local/bin/asa-autoupdate.sh and run by
# the asa-autoupdate.timer.
#
# DATA SAFETY: this only updates tracked code via `git reset --hard`. The
# per-map server data (island/ scorched/ extinction/ cluster-shared/),
# config.ini and venv/ are untracked/ignored and are never modified here.
# This script NEVER runs `git clean`. It also never restarts the ARK game
# containers or runs 04-apply-rates.sh - only the tooling services.
#
# The whole body is wrapped in a { ... } group so bash parses it fully before
# executing, making it safe even though `git reset` may rewrite this file.
#
set -euo pipefail
{
  REPO="/opt/asa-cluster"
  BRANCH="main"

  cd "${REPO}"
  exec >>"${REPO}/auto-update.log" 2>&1
  echo "==== $(date -Is) auto-update check ===="

  git fetch --prune origin "${BRANCH}"
  LOCAL="$(git rev-parse @)"
  REMOTE="$(git rev-parse "origin/${BRANCH}")"

  if [ "${LOCAL}" = "${REMOTE}" ]; then
    echo "Already up to date (${LOCAL})."
    exit 0
  fi

  echo "Updating ${LOCAL} -> ${REMOTE}"
  REQ_BEFORE="$(sha256sum bot/requirements.txt 2>/dev/null | awk '{print $1}' || true)"

  # Only touches tracked files; untracked server data is left untouched.
  git reset --hard "origin/${BRANCH}"

  REQ_AFTER="$(sha256sum bot/requirements.txt 2>/dev/null | awk '{print $1}' || true)"
  if [ "${REQ_BEFORE}" != "${REQ_AFTER}" ]; then
    echo "requirements.txt changed; updating venv"
    ./venv/bin/pip install -r bot/requirements.txt
  fi

  systemctl restart asa-bot asa-watchdog
  echo "Done. Now at $(git rev-parse @)."
  exit 0
}
