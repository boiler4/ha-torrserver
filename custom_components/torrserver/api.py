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
_FFPROBE_MIN_PRELOADED_BYTES = 64 * 1024 * 1024
_FFPROBE_TIMEOUT = 15.0


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


def _active_file_ids(
    torrent: dict[str, Any], cache_state: dict[str, Any]
) -> tuple[int, ...]:
    """Map active cache-reader piece positions to TorrServer file IDs."""
    piece_length = _as_int(cache_state.get("PiecesLength"))
    readers = cache_state.get("Readers")
    files = torrent.get("file_stats")
    if (
        piece_length <= 0
        or not isinstance(readers, list)
        or not isinstance(files, list)
    ):
        return ()

    positions = {
        _as_int(reader.get("Reader")) * piece_length
        for reader in readers
        if isinstance(reader, dict) and _as_int(reader.get("Reader")) > 0
    }
    if not positions:
        return ()

    intervals: list[tuple[int, int, int]] = []
    offset = 0
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        length = _as_int(file_info.get("length"))
        file_id = _as_int(file_info.get("id"))
        if file_id > 0 and length > 0:
            intervals.append((offset, offset + length, file_id))
        offset += length

    return tuple(
        sorted(
            {
                file_id
                for position in positions
                for start, end, file_id in intervals
                if start <= position < end
            }
        )
    )


def _probe_values(payload: dict[str, Any]) -> tuple[float, float] | None:
    """Extract bitrate and duration from TorrServer's ffprobe response."""
    format_data = payload.get("format") or payload.get("Format")
    if not isinstance(format_data, dict):
        return None
    bit_rate = _as_float(format_data.get("bit_rate") or format_data.get("BitRate"))
    duration = _as_float(
        format_data.get("duration")
        or format_data.get("duration_seconds")
        or format_data.get("DurationSeconds")
    )
    if bit_rate <= 0:
        return None
    return bit_rate, duration


@dataclass(frozen=True, slots=True)
class TorrServerData:
    """A normalized snapshot returned by TorrServer."""

    torrents: tuple[dict[str, Any], ...]
    version: str | None = None
    ffprobe_status: str = "disabled"

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
        experimental_ffprobe: bool = False,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.base_url = normalize_url(base_url)
        self._auth = BasicAuth(username, password or "") if username else None
        self._ssl = None if verify_ssl else False
        self._timeout = timeout
        self._experimental_ffprobe = experimental_ffprobe
        self._ffprobe_status = (
            "waiting_for_stream" if experimental_ffprobe else "disabled"
        )
        self._version: str | None = None
        self._probe_cache: dict[tuple[str, int], tuple[float, float]] = {}
        self._probe_attempted: set[tuple[str, int]] = set()

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

    async def async_get_media_probe(
        self, torrent_hash: str, file_id: int
    ) -> dict[str, Any]:
        """Run TorrServer's optional ffprobe endpoint."""
        payload = await self._async_request_json(
            "GET",
            f"/ffp/{torrent_hash}/{file_id}",
            request_timeout=_FFPROBE_TIMEOUT,
        )
        if not isinstance(payload, dict):
            raise TorrServerCannotConnect("Unexpected response from /ffp")
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
        cache_states: dict[str, dict[str, Any]] = {}
        for torrent, cache_result in zip(cache_targets, cache_results, strict=True):
            if isinstance(cache_result, BaseException):
                torrent["cache_stats_available"] = False
                continue
            readers = cache_result.get("Readers")
            if not isinstance(readers, list):
                readers = []
            torrent["cache_stats_available"] = True
            torrent["reader_count"] = len(readers)
            active_readers = [
                reader
                for reader in readers
                if isinstance(reader, dict) and _as_int(reader.get("Reader")) > 0
            ]
            torrent["streaming_reader_count"] = len(active_readers)
            capacity = _as_int(cache_result.get("Capacity"))
            filled = _as_int(cache_result.get("Filled"))
            piece_length = _as_int(cache_result.get("PiecesLength"))
            torrent["cache_capacity_bytes"] = capacity
            torrent["cache_filled_bytes"] = filled
            torrent["cache_fill_percent"] = (
                min(filled / capacity * 100, 100.0) if capacity > 0 else None
            )
            ahead_values = [
                max(_as_int(reader.get("End")) - _as_int(reader.get("Reader")), 0)
                * piece_length
                for reader in active_readers
                if piece_length > 0
            ]
            torrent["buffer_ahead_bytes"] = (
                min(ahead_values) if ahead_values else None
            )
            cache_states[str(torrent["hash"])] = cache_result
        if self._experimental_ffprobe:
            await self._async_apply_experimental_probe(torrents, cache_states)
        version = await self.async_get_version()
        return TorrServerData(
            torrents=torrents,
            version=version,
            ffprobe_status=self._ffprobe_status,
        )

    async def _async_apply_experimental_probe(
        self,
        torrents: tuple[dict[str, Any], ...],
        cache_states: dict[str, dict[str, Any]],
    ) -> None:
        """Apply cached metadata and attempt at most one new probe per poll."""
        pending: tuple[dict[str, Any], str, int] | None = None
        for torrent in sorted(
            torrents,
            key=lambda item: _as_float(item.get("download_speed")),
            reverse=True,
        ):
            torrent_hash = str(torrent.get("hash") or "")
            cache_state = cache_states.get(torrent_hash)
            if not torrent_hash or cache_state is None:
                continue
            file_ids = _active_file_ids(torrent, cache_state)
            if not file_ids:
                continue
            key = (torrent_hash, file_ids[0])
            if key in self._probe_cache:
                bit_rate, duration = self._probe_cache[key]
                torrent["bit_rate"] = bit_rate
                torrent["duration_seconds"] = duration
                torrent["bit_rate_source"] = "ffprobe_experimental_cached"
                torrent["ffprobe_status"] = "cached"
                self._ffprobe_status = "available"
                continue
            if (
                pending is None
                and key not in self._probe_attempted
                and _as_int(torrent.get("preloaded_bytes"))
                >= _FFPROBE_MIN_PRELOADED_BYTES
            ):
                pending = (torrent, torrent_hash, file_ids[0])

        if pending is None:
            return
        torrent, torrent_hash, file_id = pending
        key = (torrent_hash, file_id)
        self._probe_attempted.add(key)
        torrent["ffprobe_status"] = "failed"
        try:
            payload = await self.async_get_media_probe(torrent_hash, file_id)
        except TorrServerApiError:
            self._ffprobe_status = "unavailable"
            return
        values = _probe_values(payload)
        if values is None:
            self._ffprobe_status = "unavailable"
            return
        self._probe_cache[key] = values
        bit_rate, duration = values
        torrent["bit_rate"] = bit_rate
        torrent["duration_seconds"] = duration
        torrent["bit_rate_source"] = "ffprobe_experimental"
        torrent["ffprobe_status"] = "success"
        self._ffprobe_status = "available"

    async def _async_request_json(
        self,
        method: str,
        path: str,
        *,
        request_timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Request and decode JSON with consistent error handling."""
        try:
            async with asyncio.timeout(request_timeout or self._timeout):
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
