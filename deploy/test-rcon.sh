#!/usr/bin/env bash
#
# test-rcon.sh - Quick diagnostic to test RCON connectivity and broadcasts.
# Run as root: sudo bash test-rcon.sh
#
set -euo pipefail

BASE_DIR="${BASE_DIR:-/opt/asa-cluster}"
MAPS="island scorched valguero lostcolony"
ENV_FILE="${BASE_DIR}/deploy/.env"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: Missing environment config file at ${ENV_FILE}" >&2
  exit 1
fi

echo "==> Extracting admin credentials from .env..."
RCON_PASS=$(grep -E '^ADMIN_PASSWORD=' "${ENV_FILE}" | cut -d'=' -f2)

if [[ -z "${RCON_PASS}" ]]; then
  echo "Error: Could not find ADMIN_PASSWORD in ${ENV_FILE}" >&2
  exit 1
fi

echo "==> Starting RCON Broadcast Test..."
echo "--------------------------------------------------"

for m in ${MAPS}; do
  UPPER_MAP=$(echo "${m}" | tr '[:lower:]' '[:upper:]')
  PORT_VAR="${UPPER_MAP}_RCON_PORT"

  port=$(grep -E "^${PORT_VAR}=" "${ENV_FILE}" | cut -d'=' -f2 || true)

  if [[ -n "${port}" ]]; then
    echo "==> Testing [${m}] on RCON port ${port}..."

    python3 - "${port}" "${RCON_PASS}" "${m}" <<'RCONEOF'
import sys
import socket

port = int(sys.argv[1])
password = sys.argv[2]
map_name = sys.argv[3]

def send_test_broadcast(target_port, rcon_password, test_msg):
    try:
        # Create TCP socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(('127.0.0.1', target_port))

        # Authenticate Packet (Type 3)
        # ID=10, Type=3, Body=password, Terminating nulls
        auth_pkt = int.to_bytes(10, 4, 'little') + int.to_bytes(3, 4, 'little') + rcon_password.encode('utf-8') + b'\x00\x00'
        s.sendall(int.to_bytes(len(auth_pkt), 4, 'little') + auth_pkt)
        auth_resp = s.recv(4096)

        # Check if authentication was accepted (response ID should match request ID 10)
        # Sockets return length (4 bytes) + packet headers. Auth response ID is at bytes 4-8.
        if len(auth_resp) >= 8 and int.from_bytes(auth_resp[4:8], 'little') == -1:
            print(f"    [ERROR] Authentication rejected on port {target_port}. Check your password.")
            s.close()
            return

        # Command Packet (Type 2)
        # ID=11, Type=2, Body=ServerChat ..., Terminating nulls
        cmd_str = f"ServerChat {test_msg}"
        cmd_pkt = int.to_bytes(11, 4, 'little') + int.to_bytes(2, 4, 'little') + cmd_str.encode('utf-8') + b'\x00\x00'
        s.sendall(int.to_bytes(len(cmd_pkt), 4, 'little') + cmd_pkt)
        s.recv(4096)

        print(f"    [SUCCESS] Broadcast sent cleanly to {map_name.upper()}!")
        s.close()
    except socket.timeout:
        print(f"    [TIMEOUT] Container on port {target_port} is down or not responding.")
    except Exception as e:
        print(f"    [FAILED] Connection error on port {target_port}: {e}")

send_test_broadcast(port, password, f"Admin Test: RCON connection successful on the {map_name.upper()} container!")
RCONEOF
  else
    print f"    [WARNING] Missing port mapping for {m} in .env file."
  fi
done

echo "--------------------------------------------------"
echo "==> Test completed."
