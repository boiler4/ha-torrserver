"""Asynchronous client for the TorrServer HTTP API."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aiohttp import BasicAuth, ClientError, ClientSession

from .const import ACTIVE_STATES

_VERSION_PATTERN = re.compile(
    r"TorrServer\s+MatriX[.\s-]*([0-9][A-Za-z0-9._-]*)", re.IGNORECASE
)


class TorrServerApiError(Exception):
    """Base exception raised by the TorrServer client."""


class TorrServerCannotConnect(TorrServerApiError):
    """Raised when TorrServer cannot be reached or returns invalid data."""


class TorrServerAuthenticationError(TorrServerApiError):
    """Raised when TorrServer rejects the supplied credentials."""


def normalize_url(value: str) -> str:
    """Normalize and validate a TorrServer base URL."""
    value = value.strip()
    if not value:
        raise ValueError("URL is empty")
    if "://" not in value:
        value = f"http://{value}"

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use HTTP or HTTPS and include a host")
    if parsed.username or parsed.password:
        raise ValueError("Credentials must not be embedded in the URL")
    if parsed.query or parsed.fragment:
        raise ValueError("URL must not include a query or fragment")

    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _as_float(value: Any) -> float:
    """Convert a TorrServer numeric value to float."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    """Convert a TorrServer numeric value to int."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class TorrServerData:
    """A normalized snapshot returned by TorrServer."""

    torrents: tuple[dict[str, Any], ...]
    version: str | None = None

    @property
    def active_torrents(self) -> tuple[dict[str, Any], ...]:
        """Return torrents that are active in the TorrServer process."""
        return tuple(
            torrent
            for torrent in self.torrents
            if _as_int(torrent.get("stat")) in ACTIVE_STATES
        )

    @property
    def streaming_torrents(self) -> tuple[dict[str, Any], ...]:
        """Return torrents with a reader that is actually serving a stream."""
        active = self.active_torrents
        inspected = tuple(
            torrent
            for torrent in active
            if torrent.get("cache_stats_available") is True
        )
        if not inspected:
            # Compatibility fallback for TorrServer versions without /cache data.
            return active
        return tuple(
            torrent
            for torrent in inspected
            if _as_int(torrent.get("streaming_reader_count")) > 0
            or (
                _as_int(torrent.get("reader_count")) > 0
                and _as_float(torrent.get("download_speed")) >= 1024
            )
        )

    @property
    def current_torrent(self) -> dict[str, Any] | None:
        """Return the most relevant active torrent."""
        active = self.active_torrents
        if not active:
            return None
        return max(
            active,
            key=lambda torrent: (
                _as_float(torrent.get("download_speed")),
                _as_float(torrent.get("upload_speed")),
                _as_int(torrent.get("connected_seeders")),
                _as_int(torrent.get("active_peers")),
                _as_int(torrent.get("preloaded_bytes")),
                _as_int(torrent.get("bytes_read_data")),
                _as_int(torrent.get("timestamp")),
            ),
        )

    def active_sum(self, key: str) -> float:
        """Sum a numeric field over active torrents."""
        return sum(_as_float(torrent.get(key)) for torrent in self.active_torrents)

    def count_state(self, state: int) -> int:
        """Count torrents in a TorrServer state."""
        return sum(_as_int(torrent.get("stat")) == state for torrent in self.torrents)


class TorrServerApiClient:
    """Small, read-only TorrServer API client."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool = True,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.base_url = normalize_url(base_url)
        self._auth = BasicAuth(username, password or "") if username else None
        self._ssl = None if verify_ssl else False
        self._timeout = timeout
        self._version: str | None = None

    async def async_get_torrents(self) -> tuple[dict[str, Any], ...]:
        """Return the list of torrent status objects."""
        payload = await self._async_request_json(
            "POST", "/torrents", json={"action": "list"}
        )
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise TorrServerCannotConnect("Unexpected response from /torrents")
        return tuple(payload)

    async def async_get_version(self) -> str | None:
        """Return the server version parsed from the official web interface."""
        if self._version is not None:
            return self._version
        text = await self._async_request_text("GET", "/")
        match = _VERSION_PATTERN.search(text)
        if match:
            self._version = f"MatriX.{match.group(1)}"
        return self._version

    async def async_get_cache_state(self, torrent_hash: str) -> dict[str, Any]:
        """Return the officially exposed cache and reader state for a torrent."""
        payload = await self._async_request_json(
            "POST", "/cache", json={"action": "get", "hash": torrent_hash}
        )
        if not isinstance(payload, dict):
            raise TorrServerCannotConnect("Unexpected response from /cache")
        return payload

    async def async_get_data(self) -> TorrServerData:
        """Fetch a complete read-only snapshot."""
        torrents = tuple(dict(torrent) for torrent in await self.async_get_torrents())
        cache_targets = [
            torrent
            for torrent in torrents
            if _as_int(torrent.get("stat")) in ACTIVE_STATES and torrent.get("hash")
        ]
        cache_results = await asyncio.gather(
            *(
                self.async_get_cache_state(str(torrent["hash"]))
                for torrent in cache_targets
            ),
            return_exceptions=True,
        )
        for torrent, cache_result in zip(cache_targets, cache_results, strict=True):
            if isinstance(cache_result, BaseException):
                torrent["cache_stats_available"] = False
                continue
            readers = cache_result.get("Readers")
            if not isinstance(readers, list):
                readers = []
            torrent["cache_stats_available"] = True
            torrent["reader_count"] = len(readers)
            torrent["streaming_reader_count"] = sum(
                isinstance(reader, dict) and _as_int(reader.get("Reader")) > 0
                for reader in readers
            )
        version = await self.async_get_version()
        return TorrServerData(torrents=torrents, version=version)

    async def _async_request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """Request and decode JSON with consistent error handling."""
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    method,
                    f"{self.base_url}{path}",
                    auth=self._auth,
                    ssl=self._ssl,
                    **kwargs,
                ) as response:
                    self._raise_for_status(response.status)
                    return await response.json(content_type=None)
        except TorrServerApiError:
            raise
        except (TimeoutError, ClientError, ValueError) as err:
            raise TorrServerCannotConnect(str(err)) from err

    async def _async_request_text(self, method: str, path: str) -> str:
        """Request text with consistent error handling."""
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    method,
                    f"{self.base_url}{path}",
                    auth=self._auth,
                    ssl=self._ssl,
                ) as response:
                    self._raise_for_status(response.status)
                    return await response.text()
        except TorrServerApiError:
            raise
        except (TimeoutError, ClientError, UnicodeError) as err:
            raise TorrServerCannotConnect(str(err)) from err

    @staticmethod
    def _raise_for_status(status: int) -> None:
        """Translate HTTP status codes to integration exceptions."""
        if status in {401, 403}:
            raise TorrServerAuthenticationError("Authentication failed")
        if status >= 400:
            raise TorrServerCannotConnect(f"TorrServer returned HTTP {status}")
