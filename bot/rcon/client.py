from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

from . import protocol

log = logging.getLogger(__name__)

_MIN_BACKOFF = 2.0
_MAX_BACKOFF = 60.0


class RconError(Exception):
    pass


class AuthenticationError(RconError):
    pass


class RconClient:

    def __init__(self, host: str, port: int, password: str, *, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._request_id = 0
        self._connected = False

    async def connect(self) -> None:
        log.info("RCON connecting to %s:%s …", self.host, self.port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout,
        )
        await self._authenticate()
        self._connected = True
        log.info("RCON connected and authenticated.")

    async def disconnect(self) -> None:
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        log.info("RCON disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def ensure_connected(self, *, max_retries: int = 3) -> None:
        if self._connected:
            return
        backoff = _MIN_BACKOFF
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                await self.connect()
                return
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "RCON reconnect attempt %d/%d failed (%s) – retrying in %.0fs",
                    attempt + 1, max_retries, exc, backoff,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _MAX_BACKOFF)
        raise last_exc or RconError("Failed to connect to RCON")

    async def command(self, cmd: str) -> str:
        async with self._lock:
            try:
                return await self._send_command(cmd)
            except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                log.warning("RCON command failed (%s), reconnecting …", exc)
                self._connected = False
                await self.ensure_connected()
                return await self._send_command(cmd)

    def _next_id(self) -> int:
        self._request_id += 1
        if self._request_id > 0x7FFF_FFFE:
            self._request_id = 1
        return self._request_id

    async def _send_raw(self, request_id: int, packet_type: int, body: str = "") -> None:
        assert self._writer is not None
        data = protocol.encode(request_id, packet_type, body)
        self._writer.write(data)
        await self._writer.drain()

    async def _recv_packet(self) -> protocol.RconPacket:
        assert self._reader is not None
        size_data = await asyncio.wait_for(self._reader.readexactly(4), timeout=self.timeout)
        size = struct.unpack("<i", size_data)[0]
        payload = await asyncio.wait_for(self._reader.readexactly(size), timeout=self.timeout)
        full = size_data + payload
        pkt = protocol.decode(full)
        if pkt is None:
            raise RconError("Failed to decode RCON packet")
        return pkt

    async def _authenticate(self) -> None:
        req_id = self._next_id()
        await self._send_raw(req_id, protocol.SERVERDATA_AUTH, self.password)

        # server sometimes sends an empty packet before the real auth response
        for _ in range(3):
            pkt = await self._recv_packet()
            if pkt.request_id == -1:
                raise AuthenticationError(
                    "RCON authentication failed – check ServerAdminPassword."
                )
            if pkt.request_id == req_id:
                return
        raise AuthenticationError("Did not receive RCON auth response.")

    async def _send_command(self, cmd: str) -> str:
        req_id = self._next_id()
        await self._send_raw(req_id, protocol.SERVERDATA_EXECCOMMAND, cmd)

        parts: list[str] = []
        # short timeout since the server replies in ms; avoids blocking on silence
        read_timeout = min(self.timeout, 2.0)
        while True:
            try:
                pkt = await self._recv_packet_with_timeout(read_timeout)
            except asyncio.TimeoutError:
                break

            if pkt.request_id == req_id and pkt.body:
                parts.append(pkt.body)

        return "\n".join(parts) if parts else ""

    async def _recv_packet_with_timeout(self, timeout: float) -> protocol.RconPacket:
        assert self._reader is not None
        size_data = await asyncio.wait_for(self._reader.readexactly(4), timeout=timeout)
        size = struct.unpack("<i", size_data)[0]
        payload = await asyncio.wait_for(self._reader.readexactly(size), timeout=timeout)
        full = size_data + payload
        pkt = protocol.decode(full)
        if pkt is None:
            raise RconError("Failed to decode RCON packet")
        return pkt

