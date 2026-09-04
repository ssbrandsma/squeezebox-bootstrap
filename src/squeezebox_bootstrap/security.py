from __future__ import annotations

import time
from collections import Counter


class RateLimiter:
    """Bounded per-key token buckets for unauthenticated endpoints."""

    def __init__(self, requests_per_minute: int, max_keys: int = 4096) -> None:
        self.requests_per_minute = requests_per_minute
        self.max_keys = max_keys
        self._buckets: dict[str, tuple[float, float, float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        capacity = float(self.requests_per_minute)
        refill_per_second = capacity / 60
        tokens, updated, _ = self._buckets.get(key, (capacity, now, now))
        tokens = min(capacity, tokens + (now - updated) * refill_per_second)
        if tokens < 1:
            self._buckets[key] = (tokens, now, now)
            return False
        if key not in self._buckets and len(self._buckets) >= self.max_keys:
            oldest = min(self._buckets, key=lambda item: self._buckets[item][2])
            self._buckets.pop(oldest, None)
        self._buckets[key] = (tokens - 1, now, now)
        return True


class ConnectionLimiter:
    def __init__(self, maximum: int, maximum_per_ip: int) -> None:
        self.maximum = maximum
        self.maximum_per_ip = maximum_per_ip
        self.active = 0
        self.by_ip: Counter[str] = Counter()

    def acquire(self, ip: str) -> bool:
        if self.active >= self.maximum or self.by_ip[ip] >= self.maximum_per_ip:
            return False
        self.active += 1
        self.by_ip[ip] += 1
        return True

    def release(self, ip: str) -> None:
        if self.by_ip[ip] <= 1:
            self.by_ip.pop(ip, None)
        else:
            self.by_ip[ip] -= 1
        self.active = max(0, self.active - 1)
