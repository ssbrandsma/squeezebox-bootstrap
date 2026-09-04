from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppletEntry:
    name: str
    title: str
    version: str
    target: str
    url: str
    sha: str
    desc: str = ""
    creator: str = ""
    email: str = ""
    min_target_version: str | None = None
    max_target_version: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "version": self.version,
            "target": self.target,
            "url": self.url,
            "sha": self.sha.lower(),
            "desc": self.desc,
            "creator": self.creator,
            "email": self.email,
        }


@dataclass(slots=True)
class ServerConfig:
    name: str
    uuid: str
    host: str
    http_port: int
    slimproto_port: int
    discovery_port: int
    version: str
    debug_protocol: bool = False
    advertise_ip: str = ""
    public_catalog_mode: bool = False
    max_tcp_connections: int = 64
    max_tcp_connections_per_ip: int = 8
    max_comet_streams: int = 32
    max_comet_streams_per_ip: int = 2
    max_comet_sessions: int = 128
    max_players: int = 64
    max_subscriptions_per_session: int = 8
    max_pending_events: int = 32
    session_idle_seconds: int = 300
    discovery_requests_per_minute: int = 30
    http_requests_per_minute: int = 60
    slimproto_frames_per_minute: int = 240


@dataclass(slots=True)
class PlayerState:
    player_id: str
    remote_address: str
    model: str = "unknown"
    firmware: str = ""
    revision: int = 0
    capabilities: str = ""
    language: str = ""
    bytes_received: int = 0
    connected_at: float = 0.0
    last_seen: float = 0.0
    power: bool = True
    name: str = ""
    last_stat_event: str = ""


@dataclass(slots=True)
class Subscription:
    response_channel: str
    command: str
    player_id: str | None
    args: list[str]


@dataclass(slots=True)
class CometSession:
    client_id: str
    subscriptions: dict[str, Subscription] = field(default_factory=dict)
    pending_events: list[dict[str, Any]] = field(default_factory=list)
    is_streaming: bool = False
    last_activity: float = field(default_factory=time.monotonic)
