"""Asynchronous client for the TorrServer HTTP API."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aiohttp import BasicAuth, ClientError, ClientSession

from .const import ACTIVE_STATES

_LOGGER = logging.getLogger(__name__)

_VERSION_PATTERN = re.compile(
    r"TorrServer\s+MatriX[.\s-]*([0-9][A-Za-z0-9._-]*)", re.IGNORECASE
)
_FFPROBE_MIN_PRELOADED_BYTES = 64 * 1024 * 1024
_FFPROBE_TIMEOUT = 15.0
_FFPROBE_RETRY_DELAYS = (15.0, 30.0, 60.0, 120.0, 300.0)
_FFPROBE_WARNING_FAILURES = 3
_FFPROBE_CACHE_TTL = 24 * 60 * 60.0
_FFPROBE_CACHE_MAX_ENTRIES = 256


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


def _cache_readers(cache_state: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return valid reader windows, including a reader at the file start."""
    readers = cache_state.get("Readers")
    if not isinstance(readers, list):
        return ()
    return tuple(
        reader
        for reader in readers
        if isinstance(reader, dict)
        and "Reader" in reader
        and _as_int(reader.get("Reader")) >= 0
        and _as_int(reader.get("End")) > _as_int(reader.get("Start"))
    )


def _piece_states(cache_state: dict[str, Any]) -> dict[int, dict[str, Any]] | None:
    """Normalize TorrServer's cached-piece map without inventing missing data."""
    pieces = cache_state.get("Pieces")
    if not isinstance(pieces, dict):
        return None

    normalized: dict[int, dict[str, Any]] = {}
    for key, value in pieces.items():
        if not isinstance(value, dict):
            continue
        raw_id = value.get("Id", value.get("id", key))
        try:
            piece_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if piece_id >= 0:
            normalized[piece_id] = value
    return normalized


def _contiguous_completed_buffer(
    cache_state: dict[str, Any], reader: dict[str, Any]
) -> tuple[int, int] | None:
    """Return conservative bytes/pieces completed contiguously after a reader.

    TorrServer's Reader/End values describe the configured cache window, not
    downloaded data. The Pieces map is the authoritative source. The current
    piece is deliberately excluded because /cache exposes only its piece index,
    not the reader's byte offset inside that piece.
    """
    pieces = _piece_states(cache_state)
    if pieces is None:
        return None

    reader_piece = _as_int(reader.get("Reader"))
    end_piece = _as_int(reader.get("End"))
    if reader_piece < 0 or end_piece <= reader_piece:
        return (0, 0)

    current = pieces.get(reader_piece)
    if not current or not bool(current.get("Completed", current.get("completed"))):
        return (0, 0)

    default_length = _as_int(cache_state.get("PiecesLength"))
    completed_bytes = 0
    completed_pieces = 0
    for piece_id in range(reader_piece + 1, end_piece):
        piece = pieces.get(piece_id)
        if not piece or not bool(piece.get("Completed", piece.get("completed"))):
            break
        size = _as_int(piece.get("Size", piece.get("size")))
        length = _as_int(piece.get("Length", piece.get("length")))
        piece_bytes = size or length or default_length
        if length > 0 and piece_bytes > length:
            piece_bytes = length
        completed_bytes += max(piece_bytes, 0)
        completed_pieces += 1

    return completed_bytes, completed_pieces


def _active_file_ids(
    torrent: dict[str, Any], cache_state: dict[str, Any]
) -> tuple[int, ...]:
    """Map active cache-reader piece positions to TorrServer file IDs."""
    piece_length = _as_int(cache_state.get("PiecesLength"))
    readers = _cache_readers(cache_state)
    files = torrent.get("file_stats")
    if piece_length <= 0 or not readers or not isinstance(files, list):
        return ()

    positions = {_as_int(reader.get("Reader")) * piece_length for reader in readers}
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


def _active_file_size(torrent: dict[str, Any], file_id: int) -> int | None:
    """Return the selected file size without falling back to torrent size."""
    files = torrent.get("file_stats")
    if not isinstance(files, list):
        return None
    for file_info in files:
        if not isinstance(file_info, dict) or _as_int(file_info.get("id")) != file_id:
            continue
        length = _as_int(file_info.get("length"))
        return length if length > 0 else None
    return None


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


def _probe_error_code(error: TorrServerApiError | None) -> str:
    """Return a stable, privacy-safe reason for a failed probe."""
    if error is None:
        return "invalid_payload"
    message = str(error).casefold()
    if "timed out" in message:
        return "timeout"
    if "authentication" in message:
        return "authentication"
    match = re.search(r"http\s+(\d{3})", message)
    if match:
        return f"http_{match.group(1)}"
    if "unexpected response" in message:
        return "invalid_response"
    return "request_error"


@dataclass(frozen=True, slots=True)
class _ProbeCacheEntry:
    """One bounded, expiring ffprobe result."""

    bit_rate: float
    duration: float
    created_at: float


@dataclass(frozen=True, slots=True)
class _ProbeRetryState:
    """Backoff state for one torrent file."""

    failures: int
    retry_at: float
    last_failure_at: float
    error: str


@dataclass(frozen=True, slots=True)
class TorrServerData:
    """A normalized snapshot returned by TorrServer."""

    torrents: tuple[dict[str, Any], ...]
    version: str | None = None
    ffprobe_status: str = "disabled"
    ffprobe_failures: int = 0
    ffprobe_last_error: str | None = None
    ffprobe_retry_seconds: float | None = None

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
        self._probe_cache: OrderedDict[tuple[str, int], _ProbeCacheEntry] = (
            OrderedDict()
        )
        self._probe_retries: dict[tuple[str, int], _ProbeRetryState] = {}
        self._ffprobe_failures = 0
        self._ffprobe_last_error: str | None = None
        self._ffprobe_retry_seconds: float | None = None

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
            active_readers = list(_cache_readers(cache_result))
            torrent["streaming_reader_count"] = len(active_readers)
            capacity = _as_int(cache_result.get("Capacity"))
            filled = _as_int(cache_result.get("Filled"))
            torrent["cache_capacity_bytes"] = capacity
            torrent["cache_filled_bytes"] = filled
            torrent["cache_fill_percent"] = (
                min(filled / capacity * 100, 100.0) if capacity > 0 else None
            )
            contiguous = [
                measured
                for reader in active_readers
                if (measured := _contiguous_completed_buffer(cache_result, reader))
                is not None
            ]
            smallest = min(contiguous, key=lambda item: item[0]) if contiguous else None
            torrent["buffer_ahead_bytes"] = smallest[0] if smallest else None
            torrent["buffer_contiguous_completed_pieces"] = (
                smallest[1] if smallest else None
            )
            torrent["buffer_measurement_source"] = (
                "contiguous_completed_pieces" if smallest else "unavailable"
            )
            active_file_ids = _active_file_ids(torrent, cache_result)
            if (
                active_file_ids
                and (file_size := _active_file_size(torrent, active_file_ids[0]))
                is not None
            ):
                torrent["active_file_size"] = file_size
            cache_states[str(torrent["hash"])] = cache_result
        if self._experimental_ffprobe:
            await self._async_apply_experimental_probe(torrents, cache_states)
        version = await self.async_get_version()
        return TorrServerData(
            torrents=torrents,
            version=version,
            ffprobe_status=self._ffprobe_status,
            ffprobe_failures=self._ffprobe_failures,
            ffprobe_last_error=self._ffprobe_last_error,
            ffprobe_retry_seconds=self._ffprobe_retry_seconds,
        )

    def _prune_probe_state(self, now: float) -> None:
        """Bound in-memory probe results and discard stale failures."""
        for key, entry in tuple(self._probe_cache.items()):
            if now - entry.created_at >= _FFPROBE_CACHE_TTL:
                self._probe_cache.pop(key, None)
        while len(self._probe_cache) > _FFPROBE_CACHE_MAX_ENTRIES:
            self._probe_cache.popitem(last=False)

        for key, retry in tuple(self._probe_retries.items()):
            if now - retry.last_failure_at >= _FFPROBE_CACHE_TTL:
                self._probe_retries.pop(key, None)
        if len(self._probe_retries) > _FFPROBE_CACHE_MAX_ENTRIES:
            stale = sorted(
                self._probe_retries,
                key=lambda key: self._probe_retries[key].last_failure_at,
            )
            for key in stale[: len(self._probe_retries) - _FFPROBE_CACHE_MAX_ENTRIES]:
                self._probe_retries.pop(key, None)

    def _cached_probe(
        self, key: tuple[str, int], now: float
    ) -> _ProbeCacheEntry | None:
        """Return a fresh cached result and refresh its LRU position."""
        cached = self._probe_cache.get(key)
        if cached is None:
            return None
        if now - cached.created_at >= _FFPROBE_CACHE_TTL:
            self._probe_cache.pop(key, None)
            return None
        self._probe_cache.move_to_end(key)
        return cached

    def _record_probe_failure(
        self,
        key: tuple[str, int],
        *,
        now: float,
        error: TorrServerApiError | None,
    ) -> _ProbeRetryState:
        """Record one failure and schedule a bounded exponential retry."""
        previous = self._probe_retries.get(key)
        failures = (previous.failures if previous else 0) + 1
        delay = _FFPROBE_RETRY_DELAYS[min(failures - 1, len(_FFPROBE_RETRY_DELAYS) - 1)]
        retry = _ProbeRetryState(
            failures=failures,
            retry_at=now + delay,
            last_failure_at=now,
            error=_probe_error_code(error),
        )
        self._probe_retries[key] = retry
        self._ffprobe_failures = failures
        self._ffprobe_last_error = retry.error
        self._ffprobe_retry_seconds = delay
        self._ffprobe_status = (
            "unavailable" if failures >= _FFPROBE_WARNING_FAILURES else "retrying"
        )
        return retry

    async def _async_apply_experimental_probe(
        self,
        torrents: tuple[dict[str, Any], ...],
        cache_states: dict[str, dict[str, Any]],
    ) -> None:
        """Apply cached metadata and attempt at most one new probe per poll."""
        now = monotonic()
        self._prune_probe_state(now)
        pending: tuple[dict[str, Any], str, int] | None = None
        observed_keys: set[tuple[str, int]] = set()
        observed_retries: list[_ProbeRetryState] = []
        used_cache = False
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
            observed_keys.add(key)
            if (file_size := _active_file_size(torrent, file_ids[0])) is not None:
                torrent["active_file_size"] = file_size
            if (cached := self._cached_probe(key, now)) is not None:
                torrent["bit_rate"] = cached.bit_rate
                torrent["duration_seconds"] = cached.duration
                torrent["bit_rate_source"] = "ffprobe_experimental_cached"
                torrent["bit_rate_estimated"] = False
                torrent["ffprobe_status"] = "cached"
                used_cache = True
                continue
            retry = self._probe_retries.get(key)
            if retry is not None:
                retry_seconds = max(retry.retry_at - now, 0.0)
                torrent["ffprobe_status"] = "retrying"
                torrent["ffprobe_failure_count"] = retry.failures
                torrent["ffprobe_last_error"] = retry.error
                torrent["ffprobe_retry_seconds"] = round(retry_seconds, 1)
                observed_retries.append(retry)
            if (
                pending is None
                and (retry is None or retry.retry_at <= now)
                and _as_int(torrent.get("preloaded_bytes"))
                >= _FFPROBE_MIN_PRELOADED_BYTES
            ):
                pending = (torrent, torrent_hash, file_ids[0])

        if pending is None:
            if observed_retries:
                worst = max(observed_retries, key=lambda item: item.failures)
                self._ffprobe_failures = worst.failures
                self._ffprobe_last_error = worst.error
                self._ffprobe_retry_seconds = max(worst.retry_at - now, 0.0)
                self._ffprobe_status = (
                    "unavailable"
                    if worst.failures >= _FFPROBE_WARNING_FAILURES
                    else "retrying"
                )
            elif used_cache:
                self._ffprobe_status = "available"
                self._ffprobe_failures = 0
                self._ffprobe_last_error = None
                self._ffprobe_retry_seconds = None
            elif observed_keys:
                self._ffprobe_status = "waiting_for_buffer"
                self._ffprobe_failures = 0
                self._ffprobe_last_error = None
                self._ffprobe_retry_seconds = None
            else:
                self._ffprobe_status = "waiting_for_stream"
                self._ffprobe_failures = 0
                self._ffprobe_last_error = None
                self._ffprobe_retry_seconds = None
            return
        torrent, torrent_hash, file_id = pending
        key = (torrent_hash, file_id)
        torrent["ffprobe_status"] = "probing"
        _LOGGER.debug(
            "ffprobe request started preloaded_mib=%.1f active_file_mib=%s",
            _as_int(torrent.get("preloaded_bytes")) / (1024 * 1024),
            (
                round(_as_int(torrent.get("active_file_size")) / (1024 * 1024), 1)
                if torrent.get("active_file_size") is not None
                else None
            ),
        )
        try:
            payload = await self.async_get_media_probe(torrent_hash, file_id)
        except TorrServerApiError as err:
            retry = self._record_probe_failure(key, now=monotonic(), error=err)
            torrent["ffprobe_status"] = self._ffprobe_status
            torrent["ffprobe_failure_count"] = retry.failures
            torrent["ffprobe_last_error"] = retry.error
            torrent["ffprobe_retry_seconds"] = round(
                max(retry.retry_at - monotonic(), 0.0), 1
            )
            _LOGGER.debug(
                "ffprobe request failed status=%s failures=%d reason=%s "
                "retry_seconds=%.1f",
                self._ffprobe_status,
                retry.failures,
                retry.error,
                max(retry.retry_at - monotonic(), 0.0),
            )
            return
        values = _probe_values(payload)
        if values is None:
            retry = self._record_probe_failure(key, now=monotonic(), error=None)
            torrent["ffprobe_status"] = self._ffprobe_status
            torrent["ffprobe_failure_count"] = retry.failures
            torrent["ffprobe_last_error"] = retry.error
            torrent["ffprobe_retry_seconds"] = round(
                max(retry.retry_at - monotonic(), 0.0), 1
            )
            _LOGGER.debug(
                "ffprobe response rejected status=%s failures=%d reason=%s "
                "retry_seconds=%.1f",
                self._ffprobe_status,
                retry.failures,
                retry.error,
                max(retry.retry_at - monotonic(), 0.0),
            )
            return
        bit_rate, duration = values
        self._probe_cache[key] = _ProbeCacheEntry(bit_rate, duration, monotonic())
        self._probe_cache.move_to_end(key)
        self._prune_probe_state(monotonic())
        self._probe_retries.pop(key, None)
        torrent["bit_rate"] = bit_rate
        torrent["duration_seconds"] = duration
        torrent["bit_rate_source"] = "ffprobe_experimental"
        torrent["bit_rate_estimated"] = False
        torrent["ffprobe_status"] = "success"
        self._ffprobe_status = "available"
        self._ffprobe_failures = 0
        self._ffprobe_last_error = None
        self._ffprobe_retry_seconds = None
        _LOGGER.debug(
            "ffprobe request succeeded bitrate_mbps=%.2f duration_seconds=%.3f "
            "cache_entries=%d",
            bit_rate / 1_000_000,
            duration,
            len(self._probe_cache),
        )

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
        except TimeoutError as err:
            raise TorrServerCannotConnect("Request timed out") from err
        except (ClientError, ValueError) as err:
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
