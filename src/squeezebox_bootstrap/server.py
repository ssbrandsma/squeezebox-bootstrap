from __future__ import annotations

import argparse
import asyncio
import json
import logging

from .cometd import CometManager
from .config import load_config
from .discovery import start_discovery_server
from .http import create_http_handler
from .slimproto import SlimProtoService
from .state import ServerState
from .security import ConnectionLimiter
from .artwork import ArtworkBridge


def configure_logging(debug_protocol: bool, log_level: str) -> None:
    level = logging.DEBUG if debug_protocol else getattr(logging, log_level.upper())
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def run_server(config_path: str, debug_protocol: bool = False, log_level: str = "INFO") -> None:
    config, applets = load_config(config_path)
    debug_protocol = debug_protocol or config.debug_protocol
    configure_logging(debug_protocol, log_level)
    state = ServerState(config, applets)
    comet_manager = CometManager(state, debug_protocol)
    slim_service = SlimProtoService(state, debug_protocol)
    connection_limiter = ConnectionLimiter(config.max_tcp_connections, config.max_tcp_connections_per_ip)
    artwork = ArtworkBridge(config, logging.getLogger("squeezebox_bootstrap.artwork"))

    async def limited_handler(handler, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        ip = peer[0] if isinstance(peer, tuple) else "unknown"
        if not connection_limiter.acquire(ip):
            logging.getLogger("squeezebox_bootstrap.server").warning("[SECURITY] TCP connection limit peer=%s", ip)
            writer.close()
            return
        try:
            await handler(reader, writer)
        finally:
            connection_limiter.release(ip)

    discovery_transport = await start_discovery_server(config, state.traffic_metrics, debug_protocol)
    http_handler = await create_http_handler(comet_manager, debug_protocol, artwork)
    slim_server = await asyncio.start_server(
        lambda reader, writer: limited_handler(slim_service.handle_client, reader, writer),
        config.host,
        config.slimproto_port,
    )
    http_server = await asyncio.start_server(
        lambda reader, writer: limited_handler(http_handler, reader, writer), config.host, config.http_port
    )
    logging.getLogger("squeezebox_bootstrap.server").info(
        "Listening UDP %s:%d, TCP %s:%d and TCP %s:%d (protocol debug=%s, public catalog=%s)",
        config.host, config.discovery_port, config.host, config.slimproto_port, config.host, config.http_port,
        debug_protocol, config.public_catalog_mode,
    )

    async def log_metrics() -> None:
        while True:
            await asyncio.sleep(config.metrics_log_interval_seconds)
            snapshot = state.traffic_metrics.snapshot()
            if snapshot:
                logging.getLogger("squeezebox_bootstrap.metrics").info("[METRICS] traffic=%s", json.dumps(snapshot))

    async def refresh_subscriptions() -> None:
        while True:
            await asyncio.sleep(1)
            await comet_manager.refresh_subscriptions()

    async with slim_server, http_server:
        await asyncio.gather(
            slim_server.serve_forever(),
            http_server.serve_forever(),
            log_metrics(),
            refresh_subscriptions(),
        )

    discovery_transport.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal LMS-compatible bootstrap server")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--debug-protocol", action="store_true", help="Trace bounded UDP, SlimProto, and HTTP protocol payloads")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Base log level")
    return parser
