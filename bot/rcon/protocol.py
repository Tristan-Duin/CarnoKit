from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

SERVERDATA_RESPONSE_VALUE = 0
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_AUTH = 3


@dataclass(slots=True)
class RconPacket:
    request_id: int
    packet_type: int
    body: str


def encode(request_id: int, packet_type: int, body: str = "") -> bytes:
    body_bytes = body.encode("utf-8")
    payload = struct.pack("<ii", request_id, packet_type) + body_bytes + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def decode(data: bytes) -> Optional[RconPacket]:
    if len(data) < 12:
        return None

    size = struct.unpack("<i", data[:4])[0]
    if len(data) < 4 + size:
        return None

    request_id, packet_type = struct.unpack("<ii", data[4:12])
    body = data[12 : 4 + size - 2].decode("utf-8", errors="replace")
    return RconPacket(request_id=request_id, packet_type=packet_type, body=body)
