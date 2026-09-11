from __future__ import annotations

import asyncio
import logging
import socket

from .models import ServerConfig
from .metrics import TrafficMetrics
from .protocol_logging import trace_payload
from .security import RateLimiter

LOGGER = logging.getLogger("squeezebox_bootstrap.discovery")
MAX_DATAGRAM = 512


def parse_discovery_values(data: bytes) -> list[tuple[str, bytes]]:
    if not data or data[:1] not in {b"e", b"E"}:
        return []
    offset = 1
    fields: list[tuple[str, bytes]] = []
    while offset + 5 <= len(data):
        tag = data[offset : offset + 4].decode("ascii", errors="ignore")
        length = data[offset + 4]
        offset += 5
        if offset + length > len(data):
            break
        value = data[offset : offset + length]
        offset += length
        if tag:
            fields.append((tag, value))
    return fields


def parse_discovery_request(data: bytes) -> list[str]:
    return [tag for tag, _ in parse_discovery_values(data)]


def build_discovery_response(config: ServerConfig, requested_fields: list[str], advertise_ip: str = "") -> bytes:
    field_values = {
        "IPAD": advertise_ip.encode("ascii") if advertise_ip else b"",
        "NAME": config.name.encode("utf-8"),
        "JSON": str(config.http_port).encode("ascii"),
        "VERS": config.version.encode("ascii"),
        "UUID": config.uuid.encode("ascii"),
    }
    parts = [b"E"]
    for field in requested_fields:
        value = field_values.get(field)
        if value is None or len(value) > 255:
            continue
        parts.append(field.encode("ascii"))
        parts.append(bytes([len(value)]))
        parts.append(value)
    return b"".join(parts)


def resolve_advertise_ip(config: ServerConfig, remote_ip: str) -> str:
    """Find the local IPv4 address that routes back to the discovery client."""
    if config.advertise_ip:
        return config.advertise_ip
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((remote_ip, 9))
            return str(probe.getsockname()[0])
    except OSError:
        return ""


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, config: ServerConfig, metrics: TrafficMetrics, debug_protocol: bool = False) -> None:
        self.config = config
        self.metrics = metrics
        self.debug_protocol = debug_protocol
        self.transport: asyncio.DatagramTransport | None = None
        self.rate_limiter = RateLimiter(config.discovery_requests_per_minute)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        if self.debug_protocol:
            LOGGER.debug("[UDP] discovery listener started local=%s", transport.get_extra_info("sockname"))

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        values = parse_discovery_values(data)
        jvid = next((value.hex() for tag, value in values if tag == "JVID" and value), "")
        squeezebox_id = f"jvid:{jvid}" if jvid else "unknown"
        self.metrics.record(addr[0], self.config.discovery_port, "UDP", "RX", "discovery", squeezebox_id)
        if not self.rate_limiter.allow(addr[0]):
            LOGGER.warning("[SECURITY] discovery rate limit peer=%s", addr[0])
            return
        trace_payload(LOGGER, self.debug_protocol, "UDP RX", addr, "discovery", data)
        if len(data) > MAX_DATAGRAM:
            LOGGER.warning("Ignoring oversized discovery datagram from %s", addr[0])
            return
        fields = [tag for tag, _ in values]
        if not fields:
            return
        advertise_ip = resolve_advertise_ip(self.config, addr[0])
        response = build_discovery_response(self.config, fields, advertise_ip)
        if self.transport is not None:
            self.transport.sendto(response, addr)
            self.metrics.record(addr[0], self.config.discovery_port, "UDP", "TX", "discovery", squeezebox_id)
            trace_payload(LOGGER, self.debug_protocol, "UDP TX", addr, "discovery", response)
        LOGGER.info("[DISCOVERY] rx %s advertised=%s requested=%s", addr[0], advertise_ip or "none", ",".join(fields))


async def start_discovery_server(
    config: ServerConfig, metrics: TrafficMetrics, debug_protocol: bool = False
) -> asyncio.BaseTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DiscoveryProtocol(config, metrics, debug_protocol),
        local_addr=(config.host, config.discovery_port),
        family=socket.AF_INET,
        allow_broadcast=True,
    )
    return transport
