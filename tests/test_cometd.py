from __future__ import annotations

import asyncio
import unittest

from squeezebox_bootstrap.cometd import CometManager
from squeezebox_bootstrap.models import AppletEntry, ServerConfig
from squeezebox_bootstrap.state import ServerState


class CometTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config = ServerConfig("Server", "uuid", "127.0.0.1", 9000, 3483, 3483, "7.999.999")
        applets = [AppletEntry("StandaloneRadio", "Standalone Radio", "1.0", "baby", "http://1.2.3.4/a.zip", "0" * 40)]
        self.manager = CometManager(ServerState(config, applets))

    async def test_handshake(self) -> None:
        responses, streaming = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        self.assertFalse(streaming)
        self.assertTrue(responses[0]["successful"])
        self.assertIn("clientId", responses[0])

    async def test_request_requires_valid_client(self) -> None:
        responses, _ = await self.manager.handle_messages([{"channel": "/slim/request", "clientId": "deadbeef"}])
        self.assertFalse(responses[0]["successful"])

    async def test_subscribe_uses_client_id_embedded_in_response_channel(self) -> None:
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]
        responses, _ = await self.manager.handle_messages(
            [
                {
                    "id": 1,
                    "channel": "/slim/subscribe",
                    "data": {
                        "request": ["", ["serverstatus", 0, 50, "subscribe:60"]],
                        "response": f"/{client_id}/slim/serverstatus",
                    },
                }
            ]
        )
        self.assertTrue(responses[0]["successful"])
        self.assertEqual(responses[0]["clientId"], client_id)
        self.assertIn("/" + client_id + "/slim/serverstatus", self.manager.state.sessions[client_id].subscriptions)

    async def test_meta_subscribe_is_not_replayed_as_a_status_subscription(self) -> None:
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]
        responses, _ = await self.manager.handle_messages(
            [{"channel": "/meta/subscribe", "clientId": client_id, "subscription": f"/{client_id}/**"}]
        )
        self.assertTrue(responses[0]["successful"])
        self.assertFalse(self.manager.state.sessions[client_id].subscriptions)

    async def test_displaystatus_subscription_returns_an_empty_snapshot(self) -> None:
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]
        response_channel = f"/{client_id}/slim/displaystatus/player"
        await self.manager.handle_messages(
            [
                {
                    "id": 1,
                    "channel": "/slim/subscribe",
                    "data": {
                        "request": ["player", ["displaystatus"]],
                        "response": response_channel,
                    },
                }
            ]
        )
        subscription = self.manager.state.sessions[client_id].subscriptions[response_channel]
        self.assertEqual(self.manager._subscription_event(subscription)["data"], {"count": 0, "offset": 0, "item_loop": []})

    async def test_reconnect_attaches_a_stream(self) -> None:
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]
        responses, streaming = await self.manager.handle_messages(
            [{"channel": "/meta/reconnect", "clientId": client_id, "connectionType": "streaming"}],
            writer=None,
        )
        self.assertTrue(responses[0]["successful"])
        self.assertFalse(streaming)

    async def test_public_catalog_mode_only_allows_jiveapplets(self) -> None:
        self.manager.state.config.public_catalog_mode = True
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]

        rejected, _ = await self.manager.handle_messages(
            [
                {
                    "id": 1,
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {"request": ["", ["serverstatus"]]},
                }
            ]
        )
        self.assertFalse(rejected[0]["successful"])
        self.assertFalse(self.manager.state.sessions[client_id].subscriptions)
        self.assertFalse(self.manager.state.sessions[client_id].pending_events)

        allowed, _ = await self.manager.handle_messages(
            [
                {
                    "id": 2,
                    "channel": "/slim/request",
                    "clientId": client_id,
                    "data": {"request": ["", ["jiveapplets", "target:baby", "version:7.7.3"]]},
                }
            ]
        )
        self.assertTrue(allowed[0]["successful"])
        self.assertEqual(self.manager.state.sessions[client_id].pending_events[0]["data"]["count"], 1)

    async def test_session_limit_rejects_new_handshakes(self) -> None:
        self.manager.state.config.max_comet_sessions = 1
        first, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        second, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        self.assertTrue(first[0]["successful"])
        self.assertFalse(second[0]["successful"])
        self.assertEqual(second[0]["error"], "session limit reached")


if __name__ == "__main__":
    unittest.main()
