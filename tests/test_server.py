from __future__ import annotations

import unittest

from squeezebox_bootstrap.server import build_arg_parser


class ServerArgumentTests(unittest.TestCase):
    def test_debug_protocol_flag(self) -> None:
        args = build_arg_parser().parse_args(["--config", "config.json", "--debug-protocol"])
        self.assertTrue(args.debug_protocol)
        self.assertEqual(args.log_level, "INFO")


if __name__ == "__main__":
    unittest.main()
