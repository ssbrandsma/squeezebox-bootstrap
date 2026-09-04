from __future__ import annotations

import unittest

from squeezebox_bootstrap.security import ConnectionLimiter, RateLimiter


class SecurityTests(unittest.TestCase):
    def test_rate_limiter_limits_each_source_independently(self) -> None:
        limiter = RateLimiter(2)
        self.assertTrue(limiter.allow("192.0.2.1"))
        self.assertTrue(limiter.allow("192.0.2.1"))
        self.assertFalse(limiter.allow("192.0.2.1"))
        self.assertTrue(limiter.allow("192.0.2.2"))

    def test_connection_limiter_applies_global_and_per_ip_limits(self) -> None:
        limiter = ConnectionLimiter(2, 1)
        self.assertTrue(limiter.acquire("192.0.2.1"))
        self.assertFalse(limiter.acquire("192.0.2.1"))
        self.assertTrue(limiter.acquire("192.0.2.2"))
        self.assertFalse(limiter.acquire("192.0.2.3"))
        limiter.release("192.0.2.1")
        self.assertTrue(limiter.acquire("192.0.2.3"))
