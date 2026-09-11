from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from urllib.parse import parse_qs, unquote_plus, urlparse

from .cometd import CometManager, STREAM_HEARTBEAT_SECONDS
from .protocol_logging import trace_payload

LOGGER = logging.getLogger("squeezebox_bootstrap.http")
MAX_HEADER_SIZE = 16 * 1024
MAX_BODY_SIZE = 128 * 1024
READ_TIMEOUT = 15
_SQUEEZEPLAY_MODEL = re.compile(r"SqueezePlay-([^/\s]+)", re.IGNORECASE)


class HTTPProtocolError(ValueError):
    pass


async def _read_headers(reader: asyncio.StreamReader) -> bytes:
    data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=READ_TIMEOUT)
    if len(data) > MAX_HEADER_SIZE:
        raise HTTPProtocolError("headers too large")
    return data


def _parse_request(raw_headers: bytes) -> tuple[str, str, str, dict[str, str]]:
    try:
        text = raw_headers.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise HTTPProtocolError("invalid headers") from exc
    lines = text.split("\r\n")
    try:
        method, target, version = lines[0].split(" ", 2)
    except ValueError as exc:
        raise HTTPProtocolError("invalid request line") from exc
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise HTTPProtocolError("unsupported HTTP version")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise HTTPProtocolError("invalid header")
        name, value = line.split(":", 1)
        if not name or len(name) > 128:
            raise HTTPProtocolError("invalid header")
        headers[name.strip().lower()] = value.strip()
    return method, target, version, headers


async def _read_body(reader: asyncio.StreamReader, headers: dict[str, str]) -> bytes:
    try:
        content_length = int(headers.get("content-length", "0") or "0")
    except ValueError as exc:
        raise HTTPProtocolError("invalid content length") from exc
    if content_length < 0 or content_length > MAX_BODY_SIZE:
        raise HTTPProtocolError("body too large")
    if content_length == 0:
        return b""
    return await asyncio.wait_for(reader.readexactly(content_length), timeout=READ_TIMEOUT)


def _extract_messages(method: str, target: str, headers: dict[str, str], body: bytes) -> list[dict]:
    content_type = headers.get("content-type", "")
    message_payload = ""
    if method == "GET":
        parsed = urlparse(target)
        message_payload = parse_qs(parsed.query).get("message", [""])[0]
    elif "json" in content_type:
        message_payload = body.decode("utf-8")
    elif "application/x-www-form-urlencoded" in content_type:
        params = parse_qs(body.decode("utf-8"))
        message_payload = params.get("message", [""])[0]
    else:
        raise HTTPProtocolError("unsupported content type")
    try:
        parsed = json.loads(unquote_plus(message_payload) if method == "GET" else message_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPProtocolError("invalid JSON payload") from exc
    if not isinstance(parsed, list):
        raise HTTPProtocolError("Bayeux payload must be a JSON array")
    return parsed


def _add_handshake_model(messages: list[dict], headers: dict[str, str]) -> None:
    match = _SQUEEZEPLAY_MODEL.search(headers.get("user-agent", ""))
    if match is None:
        return
    for message in messages:
        if message.get("channel") == "/meta/handshake" and isinstance(message.get("ext"), dict):
            message["ext"].setdefault("model", match.group(1).lower())


async def _write_json(
    writer: asyncio.StreamWriter, status: str, payload: list[dict], close: bool = True, debug_protocol: bool = False
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = [
        f"HTTP/1.1 {status}",
        "Content-Type: application/json",
        "Expires: -1",
        "Pragma: no-cache",
        "Cache-Control: no-cache",
        f"Content-Length: {len(body)}",
        *(["Connection: close"] if close else []),
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode("ascii") + body)
    await writer.drain()
    trace_payload(LOGGER, debug_protocol, "TCP TX", writer.get_extra_info("peername"), f"HTTP {status}", body)


async def _write_streaming_headers(writer: asyncio.StreamWriter, debug_protocol: bool = False) -> None:
    headers = [
        "HTTP/1.1 200 OK",
        "Content-Type: application/json",
        "Expires: -1",
        "Pragma: no-cache",
        "Cache-Control: no-cache",
        "Transfer-Encoding: chunked",
        "Connection: keep-alive",
        "",
        "",
    ]
    writer.write("\r\n".join(headers).encode("ascii"))
    await writer.drain()
    if debug_protocol:
        LOGGER.debug("[TCP TX] HTTP streaming response peer=%s", writer.get_extra_info("peername"))


async def create_http_handler(manager: CometManager, debug_protocol: bool = False):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client_id_for_stream: str | None = None
        served_request = False
        peer = writer.get_extra_info("peername")
        if debug_protocol:
            LOGGER.debug("[TCP 9000] client connected peer=%s", peer)
        try:
            while True:
                raw_headers = await _read_headers(reader)
                method, target, _version, headers = _parse_request(raw_headers)
                peer_ip = peer[0] if isinstance(peer, tuple) else "unknown"
                if not manager.http_rate_limiter.allow(peer_ip):
                    LOGGER.warning("[SECURITY] HTTP rate limit peer=%s", peer_ip)
                    await _write_json(writer, "429 Too Many Requests", [{"successful": False, "error": "rate limit"}], debug_protocol=debug_protocol)
                    return
                trace_payload(LOGGER, debug_protocol, "TCP RX", peer, f"HTTP headers {method} {target}", raw_headers)
                parsed_target = urlparse(target)
                if parsed_target.path != "/cometd":
                    await _write_json(writer, "404 Not Found", [{"successful": False, "error": "not found"}], debug_protocol=debug_protocol)
                    return
                if manager.state.config.public_catalog_mode and (method != "POST" or "json" not in headers.get("content-type", "")):
                    await _write_json(writer, "405 Method Not Allowed", [{"successful": False, "error": "public catalog requires JSON POST"}], debug_protocol=debug_protocol)
                    return
                body = await _read_body(reader, headers)
                trace_payload(LOGGER, debug_protocol, "TCP RX", peer, "HTTP body", body)
                messages = _extract_messages(method, target, headers, body)
                _add_handshake_model(messages, headers)
                squeezebox_id = manager.player_id_for_messages(messages)
                for message in messages:
                    manager.state.traffic_metrics.record(
                        peer_ip,
                        manager.state.config.http_port,
                        "TCP",
                        "RX",
                        f"CometD:{message.get('channel') or 'unknown'}",
                        squeezebox_id,
                    )
                if debug_protocol:
                    LOGGER.debug("[TCP 9000] Bayeux channels peer=%s channels=%s", peer, [m.get("channel") for m in messages])

                for message in messages:
                    if message.get("channel") in {"/meta/connect", "/meta/reconnect"} and message.get("clientId"):
                        client_id_for_stream = str(message["clientId"])

                responses, streaming = await manager.handle_messages(messages, writer=writer)
                if streaming:
                    await _write_streaming_headers(writer, debug_protocol)
                    await manager.streams[client_id_for_stream].send(responses)  # type: ignore[index]
                    for response in responses:
                        manager.state.traffic_metrics.record(
                            peer_ip,
                            manager.state.config.http_port,
                            "TCP",
                            "TX",
                            "CometD:response",
                            squeezebox_id,
                        )
                    await manager.flush(client_id_for_stream)  # type: ignore[arg-type]
                    # SqueezePlay times out a chunked response with no bytes
                    # after roughly one minute. Send an empty Bayeux batch well
                    # before that deadline while waiting for the client to close.
                    while True:
                        try:
                            if not await asyncio.wait_for(reader.read(1), timeout=STREAM_HEARTBEAT_SECONDS):
                                return
                        except asyncio.TimeoutError:
                            if not await manager.heartbeat_stream(client_id_for_stream):  # type: ignore[arg-type]
                                return
                    return

                poll_client_id = None
                for message in messages:
                    if message.get("channel") in {"/meta/connect", "/meta/reconnect"} and message.get("clientId"):
                        poll_client_id = str(message["clientId"])
                        break
                if poll_client_id and any(m.get("channel") in {"/meta/connect", "/meta/reconnect"} for m in messages):
                    pending = await manager.wait_for_events(poll_client_id, 0)
                    if pending:
                        responses.extend(pending)
                # Jive reuses its handshake socket for the streaming request.
                await _write_json(writer, "200 OK", responses, close=False, debug_protocol=debug_protocol)
                manager.state.traffic_metrics.record(
                    peer_ip, manager.state.config.http_port, "TCP", "TX", "HTTP:response", squeezebox_id
                )
                served_request = True
        except asyncio.IncompleteReadError:
            if debug_protocol:
                LOGGER.debug("[TCP 9000] incomplete request peer=%s", peer)
        except asyncio.TimeoutError:
            if not served_request:
                await _write_json(writer, "408 Request Timeout", [{"successful": False, "error": "timeout"}], debug_protocol=debug_protocol)
        except HTTPProtocolError as exc:
            LOGGER.warning("HTTP protocol error: %s", exc)
            await _write_json(writer, "400 Bad Request", [{"successful": False, "error": str(exc)}], debug_protocol=debug_protocol)
        finally:
            if client_id_for_stream:
                await manager.detach_stream(client_id_for_stream, writer)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            if debug_protocol:
                LOGGER.debug("[TCP 9000] client disconnected peer=%s", peer)

    return handle
