from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import uuid
from collections import OrderedDict
from time import monotonic
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .security import RateLimiter


class _SafeRedirects(HTTPRedirectHandler):
    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.bridge._validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ArtworkBridge:
    def __init__(self, config, logger):
        self.config = config
        self.log = logger
        self.cache = OrderedDict()
        self.inflight = {}
        self.rate_limiter = RateLimiter(config.artwork_requests_per_minute)

    def _validate_url(self, value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("unsafe artwork URL")
        if parsed.port not in (None, 80, 443):
            raise ValueError("unsafe artwork port")
        host = parsed.hostname
        if not host:
            raise ValueError("missing artwork host")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise ValueError("artwork host cannot be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise ValueError("private artwork address")

    def _fetch(self, url: str, accept: str, limit: int | None = None) -> bytes:
        self._validate_url(url)
        request = Request(
            url,
            headers={"Accept": accept, "User-Agent": "Sjoerd's Squeezebox Bootstrap server"},
        )
        with build_opener(_SafeRedirects(self)).open(request, timeout=10) as response:
            max_bytes = limit or self.config.artwork_max_bytes
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("artwork too large")
            return data

    @staticmethod
    def _image(data: bytes) -> bool:
        return data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")

    async def _resolve(self, key: str, url: str, accept: str) -> bytes | None:
        now = monotonic()
        cached = self.cache.get(key)
        if cached and cached[0] > now:
            self.cache.move_to_end(key)
            return cached[1]
        try:
            data = await asyncio.wait_for(asyncio.to_thread(self._fetch, url, accept), 12)
            if not self._image(data):
                return None
        except (OSError, ValueError, TimeoutError) as exc:
            self.log.warning("artwork fetch failed key=%s reason=%s", key, exc)
            return None
        self.cache[key] = (now + self.config.artwork_cache_ttl_seconds, data)
        self.cache.move_to_end(key)
        while len(self.cache) > self.config.artwork_cache_max_entries:
            self.cache.popitem(last=False)
        return data

    async def get(self, kind: str, params: dict[str, str], peer_ip: str) -> bytes | None:
        if not self.rate_limiter.allow(peer_ip):
            raise PermissionError("artwork rate limit")
        if kind == "station":
            try:
                station = str(uuid.UUID(params["stationuuid"]))
            except (KeyError, ValueError):
                return None
            key = "station:" + station
            api = self.config.radio_browser_url.rstrip("/") + "/json/stations/byuuid/" + quote(station)
            try:
                record = json.loads((await asyncio.to_thread(self._fetch, api, "application/json", 128 * 1024)).decode())
                favicon = record[0].get("favicon") if isinstance(record, list) and record else record.get("favicon")
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                return None
            return await self._resolve(key, favicon, "image/*") if favicon else None
        if kind == "track" and params.get("artist") and params.get("title"):
            artist, title = params["artist"], params["title"]
            key = "track:" + artist.casefold() + "\0" + title.casefold()
            api = "https://api.lms-community.org/music/track/" + quote(title, safe="") + "/" + quote(artist, safe="") + "/cover"
            try:
                record = json.loads((await asyncio.to_thread(self._fetch, api, "application/json", 128 * 1024)).decode())
                picture = record.get("picture") if isinstance(record, dict) else None
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return None
            return await self._resolve(key, picture, "image/*") if picture else None
        return None
