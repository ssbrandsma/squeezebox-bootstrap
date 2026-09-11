from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class TrafficMetric:
    squeezebox_id: str
    ip_address: str
    port: int
    transport: str
    direction: str
    message_type: str
    count: int
    start_epoch: int
    last_seen_epoch: int

    def to_wire(self) -> dict[str, int | str]:
        return {
            "squeezebox_id": self.squeezebox_id,
            "ip_address": self.ip_address,
            "port": self.port,
            "type": self.transport,
            "direction": self.direction,
            "message_type": self.message_type,
            "count": self.count,
            "start_epoch": self.start_epoch,
            "last_updated_epoch": self.last_seen_epoch,
        }


class TrafficMetrics:
    """Bounded request counters for capacity planning and operational logs."""

    def __init__(self, max_entries: int, retention_seconds: int) -> None:
        self.max_entries = max_entries
        self.retention_seconds = retention_seconds
        self._entries: dict[tuple[str, str, int, str, str, str], TrafficMetric] = {}

    def record(
        self,
        ip_address: str,
        port: int,
        transport: str,
        direction: str,
        message_type: str,
        squeezebox_id: str = "unknown",
        now: int | None = None,
    ) -> None:
        epoch = int(time.time()) if now is None else now
        self._purge(epoch)
        key = (squeezebox_id, ip_address, port, transport, direction, message_type)
        entry = self._entries.get(key)
        if entry is None:
            if len(self._entries) >= self.max_entries:
                oldest_key = min(self._entries, key=lambda item: self._entries[item].last_seen_epoch)
                del self._entries[oldest_key]
            self._entries[key] = TrafficMetric(
                squeezebox_id, ip_address, port, transport, direction, message_type, 1, epoch, epoch
            )
            return
        entry.count += 1
        entry.last_seen_epoch = epoch

    def snapshot(self, now: int | None = None) -> list[dict[str, int | str]]:
        self._purge(int(time.time()) if now is None else now)
        return [
            entry.to_wire()
            for entry in sorted(
                self._entries.values(),
                key=lambda item: (
                    item.ip_address,
                    item.squeezebox_id,
                    item.port,
                    item.transport,
                    item.direction,
                    item.message_type,
                ),
            )
        ]

    def _purge(self, epoch: int) -> None:
        cutoff = epoch - self.retention_seconds
        stale_keys = [key for key, entry in self._entries.items() if entry.last_seen_epoch < cutoff]
        for key in stale_keys:
            del self._entries[key]
