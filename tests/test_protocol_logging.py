from __future__ import annotations

import unittest

from squeezebox_bootstrap.protocol_logging import MAX_LOGGED_PAYLOAD, payload_preview


class ProtocolLoggingTests(unittest.TestCase):
    def test_preview_is_hex_and_is_bounded(self) -> None:
        payload = b"a" * (MAX_LOGGED_PAYLOAD + 3)
        preview = payload_preview(payload)
        self.assertTrue(preview.startswith("61" * MAX_LOGGED_PAYLOAD))
        self.assertTrue(preview.endswith("...(+3 bytes)"))


if __name__ == "__main__":
    unittest.main()
