from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import sys
import time
from dataclasses import dataclass

from .models import PlayerState
from .protocol_logging import trace_payload
from .security import RateLimiter
from .state import ServerState

LOGGER = logging.getLogger("squeezebox_bootstrap.slimproto")
MAX_FRAME = 64 * 1024
READ_TIMEOUT = 30
STRM_INTERVAL = 4.0


@dataclass(slots=True)
class ParsedFrame:
    opcode: str
    payload: bytes


def parse_client_frames(buffer: bytes) -> tuple[list[ParsedFrame], bytes]:
    frames: list[ParsedFrame] = []
    offset = 0
    while len(buffer) - offset >= 8:
        opcode = buffer[offset : offset + 4].decode("ascii", errors="ignore")
        length = struct.unpack(">I", buffer[offset + 4 : offset + 8])[0]
        if length > MAX_FRAME:
            raise ValueError("SlimProto frame too large")
        if len(buffer) - offset < 8 + length:
            break
        payload = buffer[offset + 8 : offset + 8 + length]
        frames.append(ParsedFrame(opcode=opcode, payload=payload))
        offset += 8 + length
    return frames, buffer[offset:]


def build_server_frame(opcode: str, payload: bytes) -> bytes:
    if len(opcode) != 4:
        raise ValueError("opcode must be 4 bytes")
    return struct.pack(">H", len(payload) + 4) + opcode.encode("ascii") + payload


def build_strm_t() -> bytes:
    payload = struct.pack(
        ">cccccccBBBcBBBIHI",
        b"t",
        b"0",
        b"m",
        b"?",
        b"?",
        b"?",
        b"?",
        0,
        0,
        0,
        b"0",
        0,
        0,
        0,
        0,
        0,
        0,
    )
    return build_server_frame("strm", payload)


def parse_helo(payload: bytes, remote_address: str) -> PlayerState:
    if len(payload) < 20:
        raise ValueError("HELO payload too short")
    device_id = payload[0]
    revision = payload[1]
    mac_bytes = payload[2:8]
    player_id = ":".join(f"{byte:02x}" for byte in mac_bytes)
    if len(payload) >= 36:
        uuid_hex = payload[8:24].hex()
        wlan_flags, bytes_hi, bytes_lo, language = struct.unpack(">HII2s", payload[24:36])
        capabilities = payload[36:].decode("utf-8", errors="ignore")
    else:
        uuid_hex = ""
        wlan_flags, bytes_hi, bytes_lo, language = struct.unpack(">HII2s", payload[8:20])
        capabilities = payload[20:].decode("utf-8", errors="ignore")
    capability_values = {}
    for capability in capabilities.split(","):
        key, separator, value = capability.partition("=")
        if separator:
            capability_values[key.lower()] = value
    model = capability_values.get("model", f"device-{device_id}")
    return PlayerState(
        player_id=player_id,
        remote_address=remote_address,
        model=model,
        model_name=capability_values.get("modelname", model),
        firmware=uuid_hex,
        firmware_version=capability_values.get("firmware", ""),
        revision=revision,
        capabilities=capabilities,
        language=language.decode("ascii", errors="ignore"),
        bytes_received=(bytes_hi << 32) | bytes_lo,
        slimproto_connected=True,
        connected_at=time.time(),
        last_seen=time.time(),
        name=player_id,
    )


def parse_stat_event(payload: bytes) -> str:
    if len(payload) < 4:
        return ""
    return payload[:4].decode("ascii", errors="ignore")


class SlimProtoService:
    def __init__(self, state: ServerState, debug_protocol: bool = False) -> None:
        self.state = state
        self.debug_protocol = debug_protocol
        self.rate_limiter = RateLimiter(state.config.slimproto_frames_per_minute)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        remote_address = peer[0] if isinstance(peer, tuple) else "unknown"
        buffer = b""
        player_id: str | None = None
        keepalive_task: asyncio.Task[None] | None = None

        if self.debug_protocol:
            LOGGER.debug("[TCP 3483] client connected peer=%s", peer)

        async def keepalive() -> None:
            while True:
                await asyncio.sleep(STRM_INTERVAL)
                frame = build_strm_t()
                writer.write(frame)
                await writer.drain()
                self.state.traffic_metrics.record(
                    remote_address, self.state.config.slimproto_port, "TCP", "TX", "strm", player_id or "unknown"
                )
                trace_payload(LOGGER, self.debug_protocol, "TCP TX", peer, "SlimProto strm/t", frame)

        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=READ_TIMEOUT)
                if not chunk:
                    break
                trace_payload(LOGGER, self.debug_protocol, "TCP RX", peer, "SlimProto bytes", chunk)
                buffer += chunk
                frames, buffer = parse_client_frames(buffer)
                for frame in frames:
                    if not self.rate_limiter.allow(remote_address):
                        LOGGER.warning("[SECURITY] SlimProto rate limit peer=%s", remote_address)
                        return
                    trace_payload(LOGGER, self.debug_protocol, "TCP RX", peer, f"SlimProto {frame.opcode}", frame.payload)
                    if frame.opcode == "HELO":
                        player = parse_helo(frame.payload, remote_address)
                        player_id = player.player_id
                        self.state.traffic_metrics.record(
                            remote_address, self.state.config.slimproto_port, "TCP", "RX", "HELO", player.player_id
                        )
                        if not self.state.upsert_player(player):
                            LOGGER.warning("[SECURITY] player limit peer=%s", remote_address)
                            return
                        LOGGER.info("[SLIM] HELO player=%s", player.player_id)
                        if keepalive_task is None:
                            keepalive_task = asyncio.create_task(keepalive())
                    elif frame.opcode == "STAT" and player_id:
                        self.state.traffic_metrics.record(
                            remote_address, self.state.config.slimproto_port, "TCP", "RX", "STAT", player_id
                        )
                        event = parse_stat_event(frame.payload)
                        self.state.mark_seen(player_id, event)
                        if self.debug_protocol:
                            LOGGER.debug("[TCP 3483] STAT player=%s event=%s", player_id, event or "unknown")
                    elif frame.opcode == "META" and player_id:
                        self.state.traffic_metrics.record(
                            remote_address, self.state.config.slimproto_port, "TCP", "RX", "META", player_id
                        )
                        self.state.mark_seen(player_id, "META")
                        if self.debug_protocol:
                            LOGGER.debug("[TCP 3483] META player=%s", player_id)
                    else:
                        self.state.traffic_metrics.record(
                            remote_address, self.state.config.slimproto_port, "TCP", "RX", frame.opcode, player_id or "unknown"
                        )
                        if self.state.config.public_catalog_mode:
                            LOGGER.warning("[SLIM] rejected command=%s in public catalog mode", frame.opcode)
                            return
                        LOGGER.info("[SLIM] unknown command=%s len=%d", frame.opcode, len(frame.payload))
        finally:
            if keepalive_task is not None:
                keepalive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ConnectionError, OSError):
                    await keepalive_task
            if player_id is not None:
                self.state.remove_player(player_id)
            writer.close()
            # Proactor can report peer resets from an internal read callback while
            # wait_closed() is pending, producing an unhandled asyncio exception.
            if sys.platform != "win32":
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()
            if self.debug_protocol:
                LOGGER.debug("[TCP 3483] client disconnected peer=%s player=%s", peer, player_id or "unknown")
