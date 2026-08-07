"""Rolling download-speed metrics for active TorrServer streams."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


def _number(value: Any) -> float:
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _stream_key(torrent: dict[str, Any]) -> str:
    """Return a stable in-memory key without exposing it to Home Assistant."""
    for field in ("hash", "torrs_hash", "link", "title", "name"):
        if value := torrent.get(field):
            return f"{field}:{value}"
    return f"object:{id(torrent)}"


@dataclass(frozen=True, slots=True)
class StreamSample:
    """One instantaneous stream and reader-buffer sample."""

    timestamp: float
    bytes_per_second: float
    average_bytes_per_second: float | None
    buffer_ahead_bytes: float | None


class StreamSpeedTracker:
    """Keep short, in-memory speed histories for currently streamed torrents."""

    def __init__(self) -> None:
        self._samples: dict[str, deque[StreamSample]] = {}
        self._last_active_average: dict[str, float] = {}

    def apply(
        self,
        torrents: tuple[dict[str, Any], ...],
        *,
        now: float,
        window_seconds: float,
        cache_full_threshold: float,
    ) -> None:
        """Annotate streaming torrents with rolling and cache-aware metrics."""
        active_keys: set[str] = set()
        cutoff = now - max(window_seconds, 1)

        for torrent in torrents:
            key = _stream_key(torrent)
            active_keys.add(key)
            samples = self._samples.setdefault(key, deque())
            while samples and samples[0].timestamp < cutoff:
                samples.popleft()

            speed = _number(torrent.get("download_speed"))
            cache_fill_value = torrent.get("cache_fill_percent")
            cache_fill = (
                min(_number(cache_fill_value), 100.0)
                if cache_fill_value is not None
                else None
            )
            if cache_fill is None:
                preloaded = _number(torrent.get("preloaded_bytes"))
                preload_size = _number(torrent.get("preload_size"))
                cache_fill = (
                    min(preloaded / preload_size * 100, 100.0)
                    if preload_size > 0
                    else None
                )
            cache_full = cache_fill is not None and cache_fill >= cache_full_threshold
            buffer_value = torrent.get("buffer_ahead_bytes")
            buffer_ahead = (
                _number(buffer_value) if buffer_value is not None else None
            )

            # A zero while the target cache is full is an intentional TorrServer pause,
            # not evidence that the swarm cannot sustain playback.
            samples.append(
                StreamSample(
                    now,
                    speed,
                    speed if speed > 0 or not cache_full else None,
                    buffer_ahead,
                )
            )

            speed_samples = [
                sample
                for sample in samples
                if sample.average_bytes_per_second is not None
            ]
            average = (
                sum(float(sample.average_bytes_per_second) for sample in speed_samples)
                / len(speed_samples)
                if speed_samples
                else None
            )
            positive_samples = sum(
                float(sample.average_bytes_per_second) > 0
                for sample in speed_samples
            )
            buffer_samples = [
                sample for sample in samples if sample.buffer_ahead_bytes is not None
            ]
            buffer_trend: float | None = None
            if len(buffer_samples) >= 2:
                elapsed = buffer_samples[-1].timestamp - buffer_samples[0].timestamp
                if elapsed > 0:
                    buffer_trend = (
                        float(buffer_samples[-1].buffer_ahead_bytes)
                        - float(buffer_samples[0].buffer_ahead_bytes)
                    ) / elapsed

            if speed == 0 and cache_full and key in self._last_active_average:
                average = self._last_active_average[key]
                source = "held_while_cache_full"
            elif speed == 0 and cache_full and average is None:
                source = "cache_full_no_history"
            elif len(samples) < 2:
                source = "measuring"
            else:
                source = "rolling_average"

            if speed > 0 and average is not None:
                self._last_active_average[key] = average

            torrent["instant_download_speed"] = speed
            torrent["average_download_speed"] = average
            torrent["average_speed_source"] = source
            torrent["average_window_seconds"] = window_seconds
            torrent["speed_sample_count"] = len(speed_samples)
            torrent["positive_speed_sample_count"] = positive_samples
            torrent["buffer_sample_count"] = len(buffer_samples)
            torrent["buffer_trend_bytes_per_second"] = buffer_trend
            torrent["buffer_trend_source"] = (
                "rolling_trend" if buffer_trend is not None else "measuring"
            )
            torrent["cache_fill_percent"] = (
                round(cache_fill, 1) if cache_fill is not None else None
            )
            torrent["cache_full"] = cache_full
            torrent["cache_full_threshold"] = cache_full_threshold

        for stale_key in set(self._samples) - active_keys:
            self._samples.pop(stale_key, None)
            self._last_active_average.pop(stale_key, None)
