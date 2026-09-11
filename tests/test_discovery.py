from __future__ import annotations

import unittest

from squeezebox_bootstrap.discovery import build_discovery_response, parse_discovery_request, parse_discovery_values
from squeezebox_bootstrap.models import ServerConfig


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ServerConfig("Server", "uuid", "0.0.0.0", 9000, 3483, 3483, "7.999.999")

    def test_parse_request(self) -> None:
        payload = b"eNAME\x00JSON\x00VERS\x00UUID\x00JVID\x06abcdef"
        self.assertEqual(parse_discovery_request(payload)[:4], ["NAME", "JSON", "VERS", "UUID"])
        self.assertEqual(dict(parse_discovery_values(payload))["JVID"], b"abcdef")

    def test_build_response(self) -> None:
        response = build_discovery_response(self.config, ["IPAD", "NAME", "JSON"], "192.0.2.10")
        self.assertTrue(response.startswith(b"E"))
        self.assertIn(b"IPAD\x0a192.0.2.10", response)
        self.assertIn(b"NAME", response)
        self.assertIn(b"JSON", response)

    def test_ignore_invalid(self) -> None:
        self.assertEqual(parse_discovery_request(b"x"), [])


if __name__ == "__main__":
    unittest.main()
