from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable

from .models import AppletEntry, CometSession, PlayerState, ServerConfig


class ServerState:
    def __init__(self, config: ServerConfig, applets: list[AppletEntry]) -> None:
        self.config = config
        self.applets = applets
        self.players: dict[str, PlayerState] = {}
        self.sessions: dict[str, CometSession] = {}
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def notify_changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    def upsert_player(self, player: PlayerState) -> bool:
        if player.player_id not in self.players and len(self.players) >= self.config.max_players:
            return False
        now = time.time()
        if not player.connected_at:
            player.connected_at = now
        player.last_seen = now
        self.players[player.player_id] = replace(player)
        self.notify_changed()
        return True

    def mark_seen(self, player_id: str, event: str = "") -> None:
        player = self.players.get(player_id)
        if not player:
            return
        player.last_seen = time.time()
        if event:
            player.last_stat_event = event
        self.notify_changed()

    def remove_player(self, player_id: str) -> None:
        if self.players.pop(player_id, None) is not None:
            self.notify_changed()

    def get_or_create_session(self, client_id: str) -> CometSession:
        session = self.sessions.get(client_id)
        if session is None:
            session = CometSession(client_id=client_id)
            self.sessions[client_id] = session
        return session

    def remove_session(self, client_id: str) -> None:
        self.sessions.pop(client_id, None)
