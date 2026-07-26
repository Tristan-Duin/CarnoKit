#!/usr/bin/env bash
# Deploy one CI-validated commit of CarnoKit tooling. This intentionally does
# not restart, recreate, or otherwise modify the ARK game containers.
set -Eeuo pipefail

REPO="${CARNOKIT_REPO:-/opt/asa-cluster}"
BRANCH="${CARNOKIT_BRANCH:-main}"
TARGET_SHA="${1:-}"
LOCK_FILE="/run/lock/carnokit-deploy.lock"
SERVICES=(asa-bot.service asa-watchdog.service)

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || die "deployment must run as root"
[[ "${TARGET_SHA}" =~ ^[0-9a-fA-F]{40}$ ]] || die "a full commit SHA is required"
[[ -d "${REPO}/.git" ]] || die "${REPO} is not a Git checkout"

exec 9>"${LOCK_FILE}"
flock -n 9 || die "another CarnoKit deployment is already running"

cd "${REPO}"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "tracked local changes would be overwritten"
fi

log "Fetching ${TARGET_SHA} from origin/${BRANCH}"
git fetch --no-tags origin "${BRANCH}"
REMOTE_SHA="$(git rev-parse "origin/${BRANCH}")"
[[ "${TARGET_SHA,,}" == "${REMOTE_SHA,,}" ]] || die "target is not the current origin/${BRANCH} (${REMOTE_SHA})"
git cat-file -e "${TARGET_SHA}^{commit}" || die "target commit was not fetched"

PREVIOUS_SHA="$(git rev-parse HEAD)"
if [[ "${PREVIOUS_SHA}" == "${TARGET_SHA}" ]]; then
  log "Already deployed at ${TARGET_SHA}"
  exit 0
fi

REQ_BEFORE="$(sha256sum bot/requirements.txt 2>/dev/null | awk '{print $1}' || true)"
UNIT_BACKUP="$(mktemp -d /tmp/carnokit-units.XXXXXX)"
TIMER_WAS_ACTIVE=false
if systemctl is-active --quiet asa-autoupdate.timer; then
  TIMER_WAS_ACTIVE=true
fi
cleanup() { rm -rf -- "${UNIT_BACKUP}"; }
trap cleanup EXIT
for unit in asa-bot.service asa-watchdog.service asa-save-on-shutdown.service; do
  [[ -f "/etc/systemd/system/${unit}" ]] && cp -a "/etc/systemd/system/${unit}" "${UNIT_BACKUP}/${unit}"
done

rollback() {
  local status=$?
  trap - ERR
  log "Deployment failed; rolling code and service units back to ${PREVIOUS_SHA}"
  git reset --hard "${PREVIOUS_SHA}" || true
  for saved in "${UNIT_BACKUP}"/*.service; do
    [[ -e "${saved}" ]] && cp -a "${saved}" /etc/systemd/system/
  done
  systemctl daemon-reload || true
  systemctl restart "${SERVICES[@]}" || true
  if [[ "${TIMER_WAS_ACTIVE}" == true ]]; then
    systemctl enable --now asa-autoupdate.timer || true
  fi
  exit "${status}"
}
trap rollback ERR

# Prevent the legacy polling job from racing this first push deployment. It is
# restored by rollback if this deployment does not become healthy.
systemctl disable --now asa-autoupdate.timer 2>/dev/null || true

log "Deploying ${PREVIOUS_SHA} -> ${TARGET_SHA}"
git reset --hard "${TARGET_SHA}"

REQ_AFTER="$(sha256sum bot/requirements.txt 2>/dev/null | awk '{print $1}' || true)"
if [[ "${REQ_BEFORE}" != "${REQ_AFTER}" ]]; then
  log "Installing changed Python dependencies"
  "${REPO}/venv/bin/pip" install --requirement bot/requirements.txt
fi

"${REPO}/venv/bin/python" -m compileall -q bot watchdog crash_analyzer

for unit in asa-bot.service asa-watchdog.service asa-save-on-shutdown.service; do
  sed "s#/opt/asa-cluster#${REPO}#g" "deploy/systemd/${unit}" > "/etc/systemd/system/${unit}"
done
systemctl daemon-reload

systemctl restart "${SERVICES[@]}"

sleep 5
for service in "${SERVICES[@]}"; do
  systemctl is-active --quiet "${service}" || {
    systemctl status "${service}" --no-pager >&2 || true
    false
  }
done

trap - ERR
printf '%s\n' "${TARGET_SHA}" > "${REPO}/.deployed-commit"
log "Deployment healthy at ${TARGET_SHA}; ARK containers were not touched"
