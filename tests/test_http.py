from __future__ import annotations

import asyncio
import json
import unittest

from squeezebox_bootstrap.cometd import CometManager
from squeezebox_bootstrap.http import create_http_handler
from squeezebox_bootstrap.models import ServerConfig
from squeezebox_bootstrap.state import ServerState


async def _read_response(reader: asyncio.StreamReader) -> tuple[str, dict[str, str], list[dict]]:
    raw_headers = await reader.readuntil(b"\r\n\r\n")
    lines = raw_headers.decode("iso-8859-1").split("\r\n")
    headers = {name.lower(): value.strip() for name, value in (line.split(":", 1) for line in lines[1:] if line)}
    body = await reader.readexactly(int(headers["content-length"]))
    return lines[0], headers, json.loads(body)


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_connection_is_reusable(self) -> None:
        config = ServerConfig("Server", "uuid", "127.0.0.1", 9000, 3483, 3483, "7.999.999")
        manager = CometManager(ServerState(config, []))
        server = await asyncio.start_server(await create_http_handler(manager), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        request = json.dumps([{"channel": "/meta/handshake", "version": "1.0"}]).encode()
        writer.write(b"POST /cometd HTTP/1.1\r\nHost: test\r\nContent-Type: text/json\r\nContent-Length: " + str(len(request)).encode() + b"\r\n\r\n" + request)
        await writer.drain()
        _, headers, payload = await _read_response(reader)
        self.assertNotIn("connection", headers)
        self.assertTrue(payload[0]["successful"])

        client_id = payload[0]["clientId"]
        request = json.dumps([{"channel": "/meta/disconnect", "clientId": client_id}]).encode()
        writer.write(b"POST /cometd HTTP/1.1\r\nHost: test\r\nContent-Type: text/json\r\nContent-Length: " + str(len(request)).encode() + b"\r\n\r\n" + request)
        await writer.drain()
        _, _, payload = await _read_response(reader)
        self.assertTrue(payload[0]["successful"])
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()

    async def test_streaming_reconnect_uses_the_existing_client_id(self) -> None:
        config = ServerConfig("Server", "uuid", "127.0.0.1", 9000, 3483, 3483, "7.999.999")
        manager = CometManager(ServerState(config, []))
        server = await asyncio.start_server(await create_http_handler(manager), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        client_id = (await manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}]))[0][0]["clientId"]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        request = json.dumps(
            [
                {"channel": "/meta/reconnect", "clientId": client_id, "connectionType": "streaming"},
                {"channel": "/meta/subscribe", "clientId": client_id, "subscription": f"/{client_id}/**"},
            ]
        ).encode()
        writer.write(b"POST /cometd HTTP/1.1\r\nHost: test\r\nContent-Type: text/json\r\nContent-Length: " + str(len(request)).encode() + b"\r\n\r\n" + request)
        await writer.drain()

        raw_headers = await reader.readuntil(b"\r\n\r\n")
        self.assertIn(b"Transfer-Encoding: chunked", raw_headers)
        chunk_size = int((await reader.readline()).strip(), 16)
        payload = json.loads(await reader.readexactly(chunk_size))
        await reader.readexactly(2)  # Chunk terminator.
        self.assertTrue(payload[0]["successful"])
        self.assertEqual(payload[0]["channel"], "/meta/reconnect")
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(1), timeout=0.01)

        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
