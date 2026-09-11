from __future__ import annotations

import json
import ipaddress
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .models import AppletEntry, ServerConfig

_SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class ConfigError(ValueError):
    pass


def _require(value: object, message: str) -> object:
    if value in (None, ""):
        raise ConfigError(message)
    return value


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError(f"Applet URL must use http or https: {url}")
    if not parsed.netloc:
        raise ConfigError(f"Applet URL must include a host: {url}")


def _positive_int(raw: dict[str, object], key: str, default: int) -> int:
    value = int(raw.get(key) or default)
    if value < 1:
        raise ConfigError(f"server.{key} must be positive")
    return value


def _validated_uuid(value: object) -> str:
    value = _require(value, "server.uuid is required")
    if not isinstance(value, str):
        raise ConfigError("server.uuid must be a valid UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ConfigError("server.uuid must be a valid UUID") from exc


def load_config(path: str | Path) -> tuple[ServerConfig, list[AppletEntry]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    server_raw = raw.get("server") or {}
    applets_raw = raw.get("applets") or []

    server = ServerConfig(
        name=str(_require(server_raw.get("name"), "server.name is required")),
        uuid=_validated_uuid(server_raw.get("uuid")),
        host=str(server_raw.get("host") or "0.0.0.0"),
        http_port=int(server_raw.get("http_port") or 9000),
        slimproto_port=int(server_raw.get("slimproto_port") or 3483),
        discovery_port=int(server_raw.get("discovery_port") or 3483),
        version=str(_require(server_raw.get("version"), "server.version is required")),
        debug_protocol=bool(server_raw.get("debug_protocol", False)),
        advertise_ip=str(server_raw.get("advertise_ip") or ""),
        public_catalog_mode=bool(server_raw.get("public_catalog_mode", False)),
        max_tcp_connections=_positive_int(server_raw, "max_tcp_connections", 64),
        max_tcp_connections_per_ip=_positive_int(server_raw, "max_tcp_connections_per_ip", 8),
        max_comet_streams=_positive_int(server_raw, "max_comet_streams", 32),
        max_comet_streams_per_ip=_positive_int(server_raw, "max_comet_streams_per_ip", 8),
        max_comet_sessions=_positive_int(server_raw, "max_comet_sessions", 128),
        max_players=_positive_int(server_raw, "max_players", 64),
        max_subscriptions_per_session=_positive_int(server_raw, "max_subscriptions_per_session", 8),
        max_pending_events=_positive_int(server_raw, "max_pending_events", 32),
        session_idle_seconds=_positive_int(server_raw, "session_idle_seconds", 300),
        discovery_requests_per_minute=_positive_int(server_raw, "discovery_requests_per_minute", 300),
        http_requests_per_minute=_positive_int(server_raw, "http_requests_per_minute", 60),
        slimproto_frames_per_minute=_positive_int(server_raw, "slimproto_frames_per_minute", 240),
        max_metric_entries=_positive_int(server_raw, "max_metric_entries", 4096),
        metrics_retention_seconds=_positive_int(server_raw, "metrics_retention_seconds", 86400),
        metrics_log_interval_seconds=_positive_int(server_raw, "metrics_log_interval_seconds", 300),
    )
    if server.advertise_ip:
        try:
            ipaddress.IPv4Address(server.advertise_ip)
        except ipaddress.AddressValueError as exc:
            raise ConfigError("server.advertise_ip must be an IPv4 address") from exc

    applets: list[AppletEntry] = []
    for index, entry in enumerate(applets_raw):
        try:
            applet = AppletEntry(
                name=str(_require(entry.get("name"), f"applets[{index}].name is required")),
                title=str(_require(entry.get("title"), f"applets[{index}].title is required")),
                version=str(_require(entry.get("version"), f"applets[{index}].version is required")),
                target=str(_require(entry.get("target"), f"applets[{index}].target is required")),
                url=str(_require(entry.get("url"), f"applets[{index}].url is required")),
                sha=str(_require(entry.get("sha"), f"applets[{index}].sha is required")),
                desc=str(entry.get("desc") or ""),
                changes=str(entry.get("changes") or ""),
                creator=str(entry.get("creator") or ""),
                email=str(entry.get("email") or ""),
                min_target_version=entry.get("min_target_version"),
                max_target_version=entry.get("max_target_version"),
            )
        except AttributeError as exc:
            raise ConfigError(f"applets[{index}] must be an object") from exc
        _validate_url(applet.url)
        if not _SHA1_RE.match(applet.sha):
            raise ConfigError(f"applets[{index}].sha must be a 40-character SHA-1 hex string")
        applets.append(applet)

    return server, applets
