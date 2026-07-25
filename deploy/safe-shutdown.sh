#!/usr/bin/env bash
# Save every reachable ARK world, wait for disk flush, then perform a controlled
# Docker stop operation. Use this instead of direct docker restart/compose down.
set -euo pipefail

BASE_DIR="${BASE_DIR:-/opt/asa-cluster}"
CONFIG_FILE="${BASE_DIR}/config.ini"
COMPOSE_DIR="${BASE_DIR}/deploy"
FLUSH_SECONDS="${SAVE_FLUSH_SECONDS:-10}"
ACTION="${1:-}"
shift || true

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

case "${ACTION}" in
  restart|stop|down|recreate) ;;
  *)
    echo "Usage: $0 restart [container ...] | stop [container ...] | down | recreate" >&2
    exit 2
    ;;
esac

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Missing ${CONFIG_FILE}; refusing an unsaved shutdown." >&2
  exit 1
fi

echo "==> Issuing SaveWorld to every configured server"
python3 - "${CONFIG_FILE}" <<'PYEOF'
import configparser
import socket
import struct
import sys

config = configparser.ConfigParser()
config.read(sys.argv[1])
host = config.get("cluster", "rcon_host", fallback="127.0.0.1")
password = config.get("cluster", "admin_password")
keys = [key.strip() for key in config.get("servers", "list").split(",") if key.strip()]

def packet(request_id, packet_type, body):
    payload = struct.pack("<ii", request_id, packet_type) + body.encode() + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload

failed = []
for key in keys:
    section = f"server.{key}"
    name = config.get(section, "name", fallback=key)
    port = config.getint(section, "rcon_port")
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.settimeout(5)
            sock.sendall(packet(1, 3, password))
            auth = sock.recv(4096)
            if len(auth) < 12 or struct.unpack("<i", auth[4:8])[0] == -1:
                raise RuntimeError("RCON authentication rejected")
            sock.sendall(packet(2, 2, "SaveWorld"))
            sock.recv(4096)
        print(f"    [saved] {name}")
    except Exception as exc:
        # Down/crashed servers cannot be saved. Record the attempt but allow
        # recovery operations to proceed for the rest of the cluster.
        failed.append(name)
        print(f"    [unreachable] {name}: {exc}", file=sys.stderr)

if failed:
    print("Warning: SaveWorld could not reach: " + ", ".join(failed), file=sys.stderr)
PYEOF

echo "==> Waiting ${FLUSH_SECONDS}s for save data to flush"
sleep "${FLUSH_SECONDS}"
cd "${COMPOSE_DIR}"

case "${ACTION}" in
  restart)
    if [[ "$#" -gt 0 ]]; then
      docker restart "$@"
    else
      docker compose -p asa-cluster restart
    fi
    ;;
  stop)
    if [[ "$#" -gt 0 ]]; then
      docker stop "$@"
    else
      docker compose -p asa-cluster stop
    fi
    ;;
  down)
    docker compose -p asa-cluster down --remove-orphans
    ;;
  recreate)
    docker compose -p asa-cluster up -d --force-recreate --remove-orphans
    ;;
esac
