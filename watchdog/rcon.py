"""Minimal synchronous RCON client for health checks and server warnings."""

from __future__ import annotations

import logging
import socket
import struct

log = logging.getLogger("watchdog.rcon")


def _encode(req_id: int, pkt_type: int, body: str = "") -> bytes:
    payload = struct.pack("<ii", req_id, pkt_type) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def _recv(sock: socket.socket) -> tuple[int, int, str] | None:
    size_data = sock.recv(4)
    if not size_data:
        return None
    size = struct.unpack("<i", size_data)[0]
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    req_id, pkt_type = struct.unpack("<ii", data[:8])
    body = data[8:-2].decode("utf-8", errors="replace")
    return req_id, pkt_type, body


def is_alive(host: str, port: int, password: str, timeout: float = 5.0) -> bool:
    """Return True if the server accepts an RCON connection and authenticates."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.sendall(_encode(1, 3, password))
        resp = _recv(sock)
        if resp is None or resp[0] == -1:
            return False
        return True
    except Exception:
        return False
    finally:
        sock.close()


def send_command(host: str, port: int, password: str, command: str, timeout: float = 5.0) -> str:
    """Connect, authenticate, send one command, return response, disconnect."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))

        # Authenticate
        sock.sendall(_encode(1, 3, password))
        resp = _recv(sock)
        if resp is None or resp[0] == -1:
            log.warning("RCON auth failed")
            return ""

        # Send command
        sock.sendall(_encode(2, 2, command))
        resp = _recv(sock)
        return resp[2] if resp else ""

    except Exception as exc:
        log.debug("RCON command failed: %s", exc)
        return ""
    finally:
        sock.close()


def broadcast(host: str, port: int, password: str, message: str) -> None:
    """Send a Broadcast message to all players."""
    send_command(host, port, password, f"Broadcast {message}")


def save_world(host: str, port: int, password: str) -> None:
    """Trigger SaveWorld."""
    send_command(host, port, password, "SaveWorld")


def shutdown(host: str, port: int, password: str) -> None:
    """Gracefully shut down the server."""
    send_command(host, port, password, "DoExit")
