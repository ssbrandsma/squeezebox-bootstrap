from __future__ import annotations

import unittest

from squeezebox_bootstrap.metrics import TrafficMetrics


class TrafficMetricsTests(unittest.TestCase):
    def test_groups_counts_by_ip_port_and_transport(self) -> None:
        metrics = TrafficMetrics(max_entries=3, retention_seconds=60)
        metrics.record("127.0.0.1", 3483, "UDP", "RX", "discovery", "00:04:20:00:00:01", now=100)
        metrics.record("127.0.0.1", 3483, "UDP", "RX", "discovery", "00:04:20:00:00:01", now=105)
        metrics.record("127.0.0.1", 9000, "TCP", "TX", "HTTP:response", "00:04:20:00:00:01", now=110)
        self.assertEqual(
            metrics.snapshot(now=110),
            [
                {"squeezebox_id": "00:04:20:00:00:01", "ip_address": "127.0.0.1", "port": 3483, "type": "UDP", "direction": "RX", "message_type": "discovery", "count": 2, "start_epoch": 100, "last_updated_epoch": 105},
                {"squeezebox_id": "00:04:20:00:00:01", "ip_address": "127.0.0.1", "port": 9000, "type": "TCP", "direction": "TX", "message_type": "HTTP:response", "count": 1, "start_epoch": 110, "last_updated_epoch": 110},
            ],
        )

    def test_expires_inactive_rows_and_bounds_entries(self) -> None:
        metrics = TrafficMetrics(max_entries=2, retention_seconds=10)
        metrics.record("192.0.2.1", 3483, "UDP", "RX", "discovery", "one", now=100)
        metrics.record("192.0.2.2", 3483, "UDP", "RX", "discovery", "two", now=101)
        metrics.record("192.0.2.3", 9000, "TCP", "TX", "HTTP:response", "three", now=102)
        self.assertEqual([row["ip_address"] for row in metrics.snapshot(now=102)], ["192.0.2.2", "192.0.2.3"])
        self.assertEqual(metrics.snapshot(now=113), [])


if __name__ == "__main__":
    unittest.main()
