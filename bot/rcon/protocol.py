"""
Source RCON protocol implementation.

Packet structure (little-endian):
    int32  size        (byte count AFTER this field)
    int32  id          (client-chosen request id)
    int32  type        (see constants below)
    byte[] body        (null-terminated ASCII/UTF-8)
    byte   \x00        (empty-string terminator)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

# ── Packet type constants ────────────────────────────────────────────────────

SERVERDATA_RESPONSE_VALUE = 0
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_AUTH_RESPONSE = 2  # same int – context distinguishes
SERVERDATA_AUTH = 3

# Minimum valid packet: 4 (id) + 4 (type) + 1 (body nul) + 1 (pad nul) = 10
MIN_PACKET_SIZE = 10
MAX_PACKET_SIZE = 4096


@dataclass(slots=True)
class RconPacket:
    """Decoded RCON packet."""

    request_id: int
    packet_type: int
    body: str


def encode(request_id: int, packet_type: int, body: str = "") -> bytes:
    """Encode an RCON packet into bytes ready to send over TCP."""
    body_bytes = body.encode("utf-8")
    # payload = id + type + body + \x00 + \x00
    payload = struct.pack("<ii", request_id, packet_type) + body_bytes + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def decode(data: bytes) -> Optional[RconPacket]:
    """Decode a single RCON packet from a raw byte buffer.

    Returns None if *data* is too short for a valid packet.
    """
    if len(data) < 12:  # 4 (size) + 4 (id) + 4 (type)
        return None

    size = struct.unpack("<i", data[:4])[0]
    if len(data) < 4 + size:
        return None

    request_id, packet_type = struct.unpack("<ii", data[4:12])
    # Body sits between the header and the two trailing null bytes.
    body = data[12 : 4 + size - 2].decode("utf-8", errors="replace")

    return RconPacket(request_id=request_id, packet_type=packet_type, body=body)
