from __future__ import annotations

import logging

MAX_LOGGED_PAYLOAD = 256


def payload_preview(payload: bytes, limit: int = MAX_LOGGED_PAYLOAD) -> str:
    """Return a bounded, single-line representation suitable for debug logs."""
    visible = payload[:limit]
    suffix = "" if len(payload) <= limit else f"...(+{len(payload) - limit} bytes)"
    return f"{visible.hex()}{suffix}"


def trace_payload(logger: logging.Logger, enabled: bool, direction: str, peer: object, label: str, payload: bytes) -> None:
    if enabled:
        logger.debug("[%s] %s peer=%s bytes=%d data=%s", direction, label, peer, len(payload), payload_preview(payload))
