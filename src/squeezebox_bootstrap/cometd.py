from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from typing import Any

from .jive import dispatch, datestatus, firmwareupgrade, playerstatus, serverstatus
from .models import Subscription
from .protocol_logging import trace_payload
from .security import RateLimiter
from .state import ServerState

LOGGER = logging.getLogger("squeezebox_bootstrap.cometd")
PROTOCOL_VERSION = "1.0"
LONG_POLL_TIMEOUT_MS = 60_000
_CLIENT_ID_IN_CHANNEL = re.compile(r"/([0-9a-f]{8})/")


def _timestamp() -> str:
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())


class StreamingResponder:
    def __init__(self, writer: asyncio.StreamWriter, debug_protocol: bool = False) -> None:
        self.writer = writer
        self.debug_protocol = debug_protocol
        self.closed = False
        self._lock = asyncio.Lock()

    async def send(self, events: list[dict[str, Any]]) -> bool:
        if self.closed:
            return False
        payload = json.dumps(events, separators=(",", ":")).encode("utf-8")
        chunk = f"{len(payload):X}\r\n".encode("ascii") + payload + b"\r\n"
        try:
            async with self._lock:
                self.writer.write(chunk)
                await self.writer.drain()
        except (ConnectionError, OSError):
            self.closed = True
            return False
        trace_payload(
            LOGGER,
            self.debug_protocol,
            "TCP TX",
            self.writer.get_extra_info("peername"),
            "CometD streaming event",
            payload,
        )
        return True

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.writer.write(b"0\r\n\r\n")
            await self.writer.drain()
        except (ConnectionError, OSError):
            pass


class CometManager:
    def __init__(self, state: ServerState, debug_protocol: bool = False) -> None:
        self.state = state
        self.debug_protocol = debug_protocol
        self.streams: dict[str, StreamingResponder] = {}
        self.waiters: dict[str, asyncio.Event] = {}
        self.http_rate_limiter = RateLimiter(state.config.http_requests_per_minute)
        state.add_listener(self.publish_status_updates)

    def expire_sessions(self) -> None:
        cutoff = time.monotonic() - self.state.config.session_idle_seconds
        for client_id, session in list(self.state.sessions.items()):
            if not session.is_streaming and session.last_activity < cutoff:
                self.state.remove_session(client_id)

    def publish_status_updates(self) -> None:
        for client_id, session in list(self.state.sessions.items()):
            events: list[dict[str, Any]] = []
            for subscription in session.subscriptions.values():
                events.append(self._subscription_event(subscription))
            if events:
                self.enqueue(client_id, events)
                if client_id in self.streams:
                    asyncio.get_running_loop().create_task(self.flush(client_id))

    def enqueue(self, client_id: str, events: list[dict[str, Any]]) -> None:
        session = self.state.get_or_create_session(client_id)
        session.pending_events.extend(events)
        overflow = len(session.pending_events) - self.state.config.max_pending_events
        if overflow > 0:
            del session.pending_events[:overflow]
        session.last_activity = time.monotonic()
        waiter = self.waiters.get(client_id)
        if waiter is not None:
            waiter.set()

    async def attach_stream(self, client_id: str, writer: asyncio.StreamWriter) -> bool:
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if isinstance(peer, tuple) else "unknown"
        streams_for_ip = sum(
            1
            for stream in self.streams.values()
            if isinstance(stream.writer.get_extra_info("peername"), tuple)
            and stream.writer.get_extra_info("peername")[0] == peer_ip
        )
        if len(self.streams) >= self.state.config.max_comet_streams or streams_for_ip >= self.state.config.max_comet_streams_per_ip:
            LOGGER.warning("[SECURITY] Comet stream limit peer=%s", peer_ip)
            return False
        self.streams[client_id] = StreamingResponder(writer, self.debug_protocol)
        session = self.state.get_or_create_session(client_id)
        session.is_streaming = True
        session.last_activity = time.monotonic()
        if session.pending_events:
            await self.flush(client_id)
        return True

    async def detach_stream(self, client_id: str, writer: asyncio.StreamWriter | None = None) -> None:
        stream = self.streams.get(client_id)
        # A reconnect can replace the stream before the old connection's cleanup
        # runs.  The stale handler must not close the replacement stream.
        if stream is not None and writer is not None and stream.writer is not writer:
            return
        stream = self.streams.pop(client_id, None)
        if stream is not None:
            await stream.close()
        session = self.state.sessions.get(client_id)
        if session is not None:
            session.is_streaming = False
            session.last_activity = time.monotonic()

    async def flush(self, client_id: str) -> None:
        session = self.state.get_or_create_session(client_id)
        session.last_activity = time.monotonic()
        if not session.pending_events:
            return
        stream = self.streams.get(client_id)
        if stream is None:
            return
        events = list(session.pending_events)
        session.pending_events.clear()
        if not await stream.send(events):
            await self.detach_stream(client_id, stream.writer)

    async def wait_for_events(self, client_id: str, timeout_ms: int) -> list[dict[str, Any]]:
        session = self.state.get_or_create_session(client_id)
        session.last_activity = time.monotonic()
        if session.pending_events:
            events = list(session.pending_events)
            session.pending_events.clear()
            return events
        waiter = asyncio.Event()
        self.waiters[client_id] = waiter
        try:
            await asyncio.wait_for(waiter.wait(), timeout_ms / 1000)
        except asyncio.TimeoutError:
            return []
        finally:
            self.waiters.pop(client_id, None)
        events = list(session.pending_events)
        session.pending_events.clear()
        return events

    def _subscription_event(self, subscription: Subscription) -> dict[str, Any]:
        if subscription.command == "serverstatus":
            data = serverstatus(self.state)
        elif subscription.command == "status":
            if not subscription.player_id:
                data = {"error": "invalid player"}
            else:
                data = playerstatus(self.state, subscription.player_id)
        elif subscription.command == "date":
            data = datestatus()
        elif subscription.command == "firmwareupgrade":
            data = firmwareupgrade()
        else:
            # Jive subscribes to a few UI state channels during startup.  Return
            # their current snapshot rather than surfacing a benign probe as an error.
            data = dispatch(
                self.state,
                subscription.player_id,
                [subscription.command, *subscription.args],
            )
        return {"channel": subscription.response_channel, "data": data}

    def _request_event(self, response_channel: str, data: dict[str, Any], request_id: Any = None) -> dict[str, Any]:
        event: dict[str, Any] = {"channel": response_channel, "data": data}
        if request_id is not None:
            event["id"] = request_id
        return event

    def _valid_client(self, client_id: str | None) -> bool:
        return bool(client_id and client_id in self.state.sessions)

    @staticmethod
    def _client_id_from_message(message: dict[str, Any]) -> str | None:
        """LMS accepts slim requests that identify a client via its response channel."""
        client_id = message.get("clientId")
        if client_id:
            return str(client_id)
        data = message.get("data") or {}
        if not isinstance(data, dict):
            return None
        value = data.get("unsubscribe") if message.get("channel") == "/slim/unsubscribe" else data.get("response")
        if not isinstance(value, str):
            return None
        match = _CLIENT_ID_IN_CHANNEL.search(value)
        return match.group(1) if match else None

    async def handle_messages(
        self,
        messages: list[dict[str, Any]],
        writer: asyncio.StreamWriter | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        responses: list[dict[str, Any]] = []
        streaming = False
        self.expire_sessions()

        for message in messages:
            channel = message.get("channel")
            client_id = self._client_id_from_message(message)
            message_id = message.get("id")
            if self.debug_protocol:
                LOGGER.debug("[COMETD] channel=%s client=%s id=%s", channel, client_id or "new", message_id or "")

            if channel == "/meta/handshake":
                if len(self.state.sessions) >= self.state.config.max_comet_sessions:
                    responses.append(
                        {
                            "id": message_id or "",
                            "channel": channel,
                            "successful": False,
                            "error": "session limit reached",
                            "advice": {"reconnect": "retry", "interval": 5000},
                        }
                    )
                    continue
                client_id = secrets.token_hex(4)
                self.state.get_or_create_session(client_id)
                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "version": PROTOCOL_VERSION,
                        "supportedConnectionTypes": ["long-polling", "streaming"],
                        "clientId": client_id,
                        "successful": True,
                        "advice": {"reconnect": "retry", "interval": 0, "timeout": LONG_POLL_TIMEOUT_MS},
                    }
                )
                continue

            if not self._valid_client(client_id):
                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "successful": False,
                        "error": "invalid clientId",
                        "advice": {"reconnect": "handshake", "interval": 0},
                    }
                )
                continue

            session = self.state.get_or_create_session(client_id)
            session.last_activity = time.monotonic()

            if channel in {"/meta/connect", "/meta/reconnect"}:
                connection_type = message.get("connectionType") or "long-polling"
                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "clientId": client_id,
                        "successful": True,
                        "timestamp": _timestamp(),
                        "advice": {"interval": 5000 if connection_type == "streaming" else 0},
                    }
                )
                if connection_type == "streaming" and writer is not None:
                    if await self.attach_stream(client_id, writer):
                        streaming = True
                    else:
                        responses[-1].update({"successful": False, "error": "stream limit reached"})
                continue

            if channel == "/meta/disconnect":
                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "clientId": client_id,
                        "successful": True,
                        "timestamp": _timestamp(),
                    }
                )
                await self.detach_stream(client_id)
                self.state.remove_session(client_id)
                continue

            if channel == "/meta/subscribe":
                subscription_name = str(message.get("subscription") or "")
                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "clientId": client_id,
                        "subscription": subscription_name,
                        "successful": True,
                    }
                )
                continue

            if channel == "/meta/unsubscribe":
                subscription_name = str(message.get("subscription") or "")
                session.subscriptions.pop(subscription_name, None)
                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "clientId": client_id,
                        "subscription": subscription_name,
                        "successful": True,
                    }
                )
                continue

            if channel in {"/slim/request", "/slim/subscribe"}:
                data = message.get("data") or {}
                if not isinstance(data, dict):
                    responses.append(
                        {
                            "id": message_id or "",
                            "channel": channel,
                            "clientId": client_id,
                            "successful": False,
                            "error": "invalid slim request",
                        }
                    )
                    continue
                request_parts = data.get("request") or ["", []]
                if not isinstance(request_parts, list) or len(request_parts) != 2 or not isinstance(request_parts[1], list):
                    responses.append(
                        {
                            "id": message_id or "",
                            "channel": channel,
                            "clientId": client_id,
                            "successful": False,
                            "error": "invalid slim request",
                        }
                    )
                    continue
                player_id = request_parts[0] or None
                command_args = request_parts[1] or []
                command = str(command_args[0]) if command_args else ""
                if self.state.config.public_catalog_mode and command != "jiveapplets":
                    responses.append(
                        {
                            "id": message_id or "",
                            "channel": channel,
                            "clientId": client_id,
                            "successful": False,
                            "error": "public catalog mode only permits jiveapplets",
                        }
                    )
                    continue
                response_channel = str(data.get("response") or f"/{client_id}/slim/request")
                result = dispatch(self.state, player_id, command_args)

                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "clientId": client_id,
                        "successful": True,
                    }
                )

                if channel == "/slim/subscribe":
                    if (
                        response_channel not in session.subscriptions
                        and len(session.subscriptions) >= self.state.config.max_subscriptions_per_session
                    ):
                        responses[-1].update({"successful": False, "error": "subscription limit reached"})
                        continue
                    subscription_command = command
                    session.subscriptions[response_channel] = Subscription(
                        response_channel=response_channel,
                        command=subscription_command,
                        player_id=player_id,
                        args=[str(item) for item in command_args[1:]],
                    )

                self.enqueue(client_id, [self._request_event(response_channel, result, message_id)])
                await self.flush(client_id)
                continue

            if channel == "/slim/unsubscribe":
                data = message.get("data") or {}
                subscription_name = str(data.get("unsubscribe") or "")
                session.subscriptions.pop(subscription_name, None)
                responses.append(
                    {
                        "id": message_id or "",
                        "channel": channel,
                        "clientId": client_id,
                        "successful": True,
                    }
                )
                continue

            responses.append(
                {
                    "id": message_id or "",
                    "channel": channel,
                    "successful": False,
                    "error": "unsupported channel",
                }
            )

        return responses, streaming
