from __future__ import annotations

import unittest

from squeezebox_bootstrap.jive import jiveapplets, serverstatus
from squeezebox_bootstrap.models import AppletEntry, ServerConfig
from squeezebox_bootstrap.state import ServerState


class JiveAppletTests(unittest.TestCase):
    def setUp(self) -> None:
        config = ServerConfig("Server", "uuid", "127.0.0.1", 9000, 3483, 3483, "7.999.999")
        applets = [
            AppletEntry("A", "Alpha", "1.0", "baby", "http://1.2.3.4/a.zip", "0" * 40),
            AppletEntry("B", "Beta", "1.0", "fab4", "http://1.2.3.4/b.zip", "1" * 40),
        ]
        self.state = ServerState(config, applets)

    def test_target_filter(self) -> None:
        result = jiveapplets(self.state, "baby", "7.7.3")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["item_loop"][0]["name"], "A")

    def test_empty_result(self) -> None:
        result = jiveapplets(self.state, "controller", "7.7.3")
        self.assertEqual(result["count"], 0)

    def test_serverstatus_uses_advertised_address(self) -> None:
        self.state.config.advertise_ip = "192.0.2.10"
        self.assertEqual(serverstatus(self.state)["ip"], "192.0.2.10")


if __name__ == "__main__":
    unittest.main()
