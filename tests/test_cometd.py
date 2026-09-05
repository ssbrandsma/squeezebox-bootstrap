from __future__ import annotations

import asyncio
import time
import unittest

from squeezebox_bootstrap.cometd import CometManager
from squeezebox_bootstrap.jive import serverstatus
from squeezebox_bootstrap.models import AppletEntry, ServerConfig
from squeezebox_bootstrap.state import ServerState


class CometTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config = ServerConfig("Server", "uuid", "127.0.0.1", 9000, 3483, 3483, "7.999.999")
        applets = [AppletEntry("StandaloneRadio", "Standalone Radio", "1.0", "baby", "http://1.2.3.4/a.zip", "0" * 40)]
        self.manager = CometManager(ServerState(config, applets))

    async def test_handshake(self) -> None:
        responses, streaming = await self.manager.handle_messages(
            [
                {
                    "channel": "/meta/handshake",
                    "version": "1.0",
                    "ext": {"mac": "00:04:20:29:16:7f", "uuid": "device-uuid"},
                }
            ]
        )
        self.assertFalse(streaming)
        self.assertTrue(responses[0]["successful"])
        self.assertIn("clientId", responses[0])
        self.assertIn("00:04:20:29:16:7f", self.manager.state.players)
        player = serverstatus(self.manager.state)["players_loop"][0]
        self.assertEqual(player["playerindex"], "0")
        self.assertEqual(player["isplayer"], 1)
        self.assertEqual(player["uuid"], "device-uuid")
        self.assertEqual(player["connected"], 0)

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

    async def test_date_subscription_returns_an_epoch_on_the_requested_channel(self) -> None:
        handshake, _ = await self.manager.handle_messages(
            [{"channel": "/meta/handshake", "version": "1.0", "ext": {"mac": "00:04:20:29:16:7f"}}]
        )
        client_id = handshake[0]["clientId"]
        response_channel = f"/{client_id}/slim/datestatus/00:04:20:29:16:7f"
        before = time.time()
        responses, _ = await self.manager.handle_messages(
            [
                {
                    "id": 5,
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {
                        "request": ["00:04:20:29:16:7f", ["date", "subscribe:3600"]],
                        "response": response_channel,
                    },
                }
            ]
        )
        event = self.manager.state.sessions[client_id].pending_events[-1]
        self.assertTrue(responses[0]["successful"])
        self.assertEqual(event["channel"], response_channel)
        self.assertEqual(event["id"], 5)
        self.assertEqual(event["data"]["date"], "0000-00-00T00:00:00+00:00")
        self.assertGreaterEqual(event["data"]["date_epoch"], int(before))

    async def test_subscription_refreshes_only_after_its_requested_interval(self) -> None:
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]
        response_channel = f"/{client_id}/slim/datestatus"
        await self.manager.handle_messages(
            [
                {
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {"request": ["", ["date", "subscribe:3600"]], "response": response_channel},
                }
            ]
        )
        session = self.manager.state.sessions[client_id]
        session.pending_events.clear()
        await self.manager.refresh_subscriptions()
        self.assertFalse(session.pending_events)
        session.subscriptions[response_channel].next_refresh_at = 0
        await self.manager.refresh_subscriptions()
        self.assertEqual(session.pending_events[0]["channel"], response_channel)

    async def test_static_subscription_does_not_refresh_even_if_the_client_requests_it(self) -> None:
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]
        response_channel = f"/{client_id}/slim/firmwarestatus"
        await self.manager.handle_messages(
            [
                {
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {"request": ["", ["firmwareupgrade", "subscribe:1"]], "response": response_channel},
                }
            ]
        )
        subscription = self.manager.state.sessions[client_id].subscriptions[response_channel]
        self.assertIsNone(subscription.refresh_interval_seconds)

    async def test_reconnect_attaches_a_stream(self) -> None:
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]
        responses, streaming = await self.manager.handle_messages(
            [{"channel": "/meta/reconnect", "clientId": client_id, "connectionType": "streaming"}],
            writer=None,
        )
        self.assertTrue(responses[0]["successful"])
        self.assertFalse(streaming)

    async def test_public_catalog_mode_allows_required_startup_probes(self) -> None:
        self.manager.state.config.public_catalog_mode = True
        handshake, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        client_id = handshake[0]["clientId"]

        serverstatus, _ = await self.manager.handle_messages(
            [
                {
                    "id": 1,
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {"request": ["", ["serverstatus"]]},
                }
            ]
        )
        self.assertTrue(serverstatus[0]["successful"])
        self.assertEqual(len(self.manager.state.sessions[client_id].subscriptions), 1)

        firmware, _ = await self.manager.handle_messages(
            [
                {
                    "id": 2,
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {"request": ["", ["firmwareupgrade"]]},
                }
            ]
        )
        self.assertTrue(firmware[0]["successful"])

        date, _ = await self.manager.handle_messages(
            [
                {
                    "id": 3,
                    "channel": "/slim/request",
                    "clientId": client_id,
                    "data": {"request": ["", ["date"]]},
                }
            ]
        )
        self.assertTrue(date[0]["successful"])
        self.assertIn("date_epoch", self.manager.state.sessions[client_id].pending_events[-1]["data"])

        menu, _ = await self.manager.handle_messages(
            [
                {
                    "id": 4,
                    "channel": "/slim/request",
                    "clientId": client_id,
                    "data": {"request": ["", ["menu"]]},
                }
            ]
        )
        self.assertTrue(menu[0]["successful"])

        status, _ = await self.manager.handle_messages(
            [
                {
                    "id": 5,
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {"request": ["player", ["status", "-", 10, "menu:menu", "useContextMenu:1"]]},
                }
            ]
        )
        self.assertTrue(status[0]["successful"])

        displaystatus, _ = await self.manager.handle_messages(
            [
                {
                    "id": 6,
                    "channel": "/slim/subscribe",
                    "clientId": client_id,
                    "data": {"request": ["player", ["displaystatus"]]},
                }
            ]
        )
        self.assertTrue(displaystatus[0]["successful"])

        rejected, _ = await self.manager.handle_messages(
            [
                {
                    "id": 7,
                    "channel": "/slim/request",
                    "clientId": client_id,
                    "data": {"request": ["", ["power", "1"]]},
                }
            ]
        )
        self.assertFalse(rejected[0]["successful"])

        allowed, _ = await self.manager.handle_messages(
            [
                {
                    "id": 8,
                    "channel": "/slim/request",
                    "clientId": client_id,
                    "data": {"request": ["", ["jiveapplets", "target:baby", "version:7.7.3"]]},
                }
            ]
        )
        self.assertTrue(allowed[0]["successful"])
        self.assertEqual(self.manager.state.sessions[client_id].pending_events[-1]["data"]["count"], 1)

    async def test_session_limit_rejects_new_handshakes(self) -> None:
        self.manager.state.config.max_comet_sessions = 1
        first, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        second, _ = await self.manager.handle_messages([{"channel": "/meta/handshake", "version": "1.0"}])
        self.assertTrue(first[0]["successful"])
        self.assertFalse(second[0]["successful"])
        self.assertEqual(second[0]["error"], "session limit reached")


if __name__ == "__main__":
    unittest.main()
