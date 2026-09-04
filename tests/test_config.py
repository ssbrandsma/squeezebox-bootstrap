from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from squeezebox_bootstrap.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    UUID = "11111111-2222-4333-8444-555555555555"

    def _write(self, payload: dict) -> Path:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            return Path(handle.name)

    def test_load_valid_config(self) -> None:
        path = self._write(
            {
                "server": {"name": "x", "uuid": self.UUID, "version": "7.9", "http_port": 9000},
                "applets": [{"name": "a", "title": "A", "version": "1", "target": "baby", "url": "http://1.2.3.4/a.zip", "sha": "0" * 40}],
            }
        )
        server, applets = load_config(path)
        self.assertEqual(server.http_port, 9000)
        self.assertEqual(applets[0].name, "a")

    def test_reject_invalid_sha(self) -> None:
        path = self._write(
            {
                "server": {"name": "x", "uuid": self.UUID, "version": "7.9"},
                "applets": [{"name": "a", "title": "A", "version": "1", "target": "baby", "url": "http://1.2.3.4/a.zip", "sha": "bad"}],
            }
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_load_public_catalog_mode(self) -> None:
        path = self._write(
            {
                "server": {"name": "x", "uuid": self.UUID, "version": "7.9", "public_catalog_mode": True},
                "applets": [],
            }
        )
        server, _ = load_config(path)
        self.assertTrue(server.public_catalog_mode)

    def test_reject_missing_uuid(self) -> None:
        path = self._write({"server": {"name": "x", "version": "7.9"}, "applets": []})
        with self.assertRaisesRegex(ConfigError, "server.uuid is required"):
            load_config(path)

    def test_reject_malformed_uuid(self) -> None:
        path = self._write({"server": {"name": "x", "uuid": "not-a-uuid", "version": "7.9"}, "applets": []})
        with self.assertRaisesRegex(ConfigError, "server.uuid must be a valid UUID"):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
