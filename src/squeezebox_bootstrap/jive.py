from __future__ import annotations

import time
from typing import Any

from .models import AppletEntry
from .state import ServerState


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in value.split("."):
        try:
            parts.append(int(token))
        except ValueError:
            break
    return tuple(parts)


def _applet_matches(applet: AppletEntry, target: str | None, version: str | None) -> bool:
    if target and applet.target != target:
        return False
    if version and applet.min_target_version and _version_tuple(version) < _version_tuple(applet.min_target_version):
        return False
    if version and applet.max_target_version and _version_tuple(version) > _version_tuple(applet.max_target_version):
        return False
    return True


def serverstatus(state: ServerState) -> dict[str, Any]:
    players_loop = [
        {
            "playerindex": str(index),
            "playerid": player.player_id,
            # SlimProto calls this device identifier the firmware UUID; Jive
            # uses it to associate its current player with serverstatus.
            "uuid": player.firmware,
            "name": player.name or player.player_id,
            "model": player.model,
            "modelname": player.model_name or player.model,
            # SqueezePlay only promotes entries marked as players to its
            # current-player state, which starts its date subscription.
            "isplayer": 1,
            "connected": 1 if player.slimproto_connected else 0,
            "power": 1 if player.power else 0,
            "firmware": player.firmware_version or str(player.revision),
            "ip": player.remote_address,
            "seq_no": 0,
            "displaytype": "none",
            "isplaying": 0,
            "canpoweroff": 1,
        }
        for index, player in enumerate(state.players.values())
    ]
    return {
        "httpport": str(state.config.http_port),
        # Never advertise the wildcard listener address to Jive clients.
        "ip": state.config.advertise_ip or state.config.host,
        "version": state.config.version,
        "uuid": state.config.uuid,
        "player count": len(players_loop),
        "players_loop": players_loop,
    }


def playerstatus(state: ServerState, player_id: str) -> dict[str, Any]:
    player = state.players.get(player_id)
    if player is None:
        return {"error": "invalid player"}
    return {
        "player_name": player.name or player.player_id,
        "player_connected": 1 if player.slimproto_connected else 0,
        "player_ip": player.remote_address,
        "power": 1 if player.power else 0,
        "mode": "stop",
        "remote": 0,
        "rate": 1,
        "player_needs_upgrade": 0,
        "player_is_upgrading": 0,
    }


def datestatus() -> dict[str, Any]:
    now = int(time.time())
    return {"date_epoch": now, "date": "0000-00-00T00:00:00+00:00"}


def firmwareupgrade() -> dict[str, Any]:
    """Report that this bootstrap server does not offer firmware updates."""
    return {"firmwareupgrade": 0, "player_needs_upgrade": 0, "player_is_upgrading": 0}


def emptymenu() -> dict[str, Any]:
    """Provide the minimal, valid response for Jive's initial menu probes."""
    return {"count": 0, "offset": 0, "item_loop": []}


def jiveapplets(state: ServerState, target: str | None, version: str | None) -> dict[str, Any]:
    entries = [applet.to_wire() for applet in state.applets if _applet_matches(applet, target, version)]
    entries.sort(key=lambda item: item["title"].lower())
    return {"count": len(entries), "item_loop": entries}


def dispatch(state: ServerState, player_id: str | None, args: list[Any]) -> dict[str, Any]:
    if not args:
        return {"error": "empty request"}
    command = str(args[0])
    tail = [str(item) for item in args[1:]]
    params: dict[str, str] = {}
    for item in tail:
        if ":" in item:
            key, value = item.split(":", 1)
            params[key] = value

    if command == "serverstatus":
        return serverstatus(state)
    if command == "status":
        if not player_id:
            return {"error": "invalid player"}
        return playerstatus(state, player_id)
    if command == "date":
        return datestatus()
    if command == "firmwareupgrade":
        return firmwareupgrade()
    if command in {"menu", "menustatus", "displaystatus"}:
        return emptymenu()
    if command == "jiveapplets":
        return jiveapplets(state, params.get("target"), params.get("version"))
    return {"count": 0, "item_loop": [], "error": f"unsupported command: {command}"}
