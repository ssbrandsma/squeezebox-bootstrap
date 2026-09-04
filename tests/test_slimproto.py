from __future__ import annotations

import struct
import unittest

from squeezebox_bootstrap.slimproto import build_server_frame, parse_client_frames, parse_helo


class SlimProtoTests(unittest.TestCase):
    def test_parse_multiple_frames(self) -> None:
        frame1 = b"HELO" + struct.pack(">I", 20) + bytes(range(20))
        frame2 = b"META" + struct.pack(">I", 4) + b"test"
        frames, remaining = parse_client_frames(frame1 + frame2)
        self.assertEqual(len(frames), 2)
        self.assertEqual(remaining, b"")

    def test_parse_partial_frame(self) -> None:
        frame = b"HELO" + struct.pack(">I", 20) + bytes(range(10))
        frames, remaining = parse_client_frames(frame)
        self.assertEqual(len(frames), 0)
        self.assertEqual(remaining, frame)

    def test_parse_helo(self) -> None:
        payload = bytes([12, 7, 0, 4, 32, 1, 2, 3]) + struct.pack(">HII2s", 0, 0, 0, b"EN")
        player = parse_helo(payload, "192.0.2.10")
        self.assertEqual(player.player_id, "00:04:20:01:02:03")
        self.assertEqual(player.revision, 7)

    def test_build_server_frame(self) -> None:
        frame = build_server_frame("strm", b"1234")
        self.assertEqual(frame[:2], struct.pack(">H", 8))

    def test_build_server_redirect_frame(self) -> None:
        self.assertEqual(build_server_frame("serv", bytes((10, 230, 94, 87))), b"\x00\x08serv\x0a\xe6\x5e\x57")


if __name__ == "__main__":
    unittest.main()
