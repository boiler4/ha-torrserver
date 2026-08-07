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
class SpeedSample:
    """One instantaneous download-speed sample."""

    timestamp: float
    bytes_per_second: float


class StreamSpeedTracker:
    """Keep short, in-memory speed histories for currently streamed torrents."""

    def __init__(self) -> None:
        self._samples: dict[str, deque[SpeedSample]] = {}
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
            preloaded = _number(torrent.get("preloaded_bytes"))
            preload_size = _number(torrent.get("preload_size"))
            cache_fill = (
                min(preloaded / preload_size * 100, 100.0) if preload_size > 0 else None
            )
            cache_full = cache_fill is not None and cache_fill >= cache_full_threshold

            # A zero while the target cache is full is an intentional TorrServer pause,
            # not evidence that the swarm cannot sustain playback.
            if speed > 0 or not cache_full:
                samples.append(SpeedSample(now, speed))

            average = (
                sum(sample.bytes_per_second for sample in samples) / len(samples)
                if samples
                else None
            )
            positive_samples = sum(sample.bytes_per_second > 0 for sample in samples)

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
            torrent["speed_sample_count"] = len(samples)
            torrent["positive_speed_sample_count"] = positive_samples
            torrent["cache_fill_percent"] = (
                round(cache_fill, 1) if cache_fill is not None else None
            )
            torrent["cache_full"] = cache_full
            torrent["cache_full_threshold"] = cache_full_threshold

        for stale_key in set(self._samples) - active_keys:
            self._samples.pop(stale_key, None)
            self._last_active_average.pop(stale_key, None)
