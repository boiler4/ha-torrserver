"""Buffer-first streaming health for active TorrServer readers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

DEFAULT_BIT_RATE_BPS: Final = 8_000_000
EMERGENCY_BUFFER_SECONDS: Final = 5.0
BUFFER_TREND_TOLERANCE_RATIO: Final = 0.05

STREAM_HEALTH_OPTIONS: Final = [
    "idle",
    "insufficient",
    "stable",
    "protected",
    "measuring",
    "unknown",
]
STREAM_BUFFER_MODE_OPTIONS: Final = [
    "idle",
    "full",
    "preloading",
    "stable",
    "draining",
    "recovering",
    "measuring",
    "unknown",
    "multiple",
]
STREAM_HEALTH_ICONS: Final = {
    "idle": "mdi:minus-circle-outline",
    "insufficient": "mdi:alert-circle",
    "stable": "mdi:check-circle-outline",
    "protected": "mdi:shield-check",
    "measuring": "mdi:timer-sand",
    "unknown": "mdi:help-circle-outline",
}
_STATE_PRIORITY: Final = {
    "protected": 0,
    "unknown": 1,
    "measuring": 1,
    "stable": 1,
    "insufficient": 2,
}


def _as_float(value: Any) -> float:
    """Convert a TorrServer value to a non-negative float."""
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    """Convert an optional numeric value without turning missing into zero."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    """Convert a TorrServer value to a non-negative integer."""
    return round(_as_float(value))


def _stream_key(torrent: Mapping[str, Any]) -> str:
    """Return an in-memory stream key that is never exposed as an attribute."""
    for field in ("hash", "torrs_hash", "link", "title", "name"):
        if value := torrent.get(field):
            return f"{field}:{value}"
    return f"object:{id(torrent)}"


def _bit_rate(torrent: Mapping[str, Any]) -> tuple[float, str]:
    """Return the best available bitrate and explain where it came from."""
    bit_rate = _as_float(torrent.get("bit_rate"))
    if bit_rate > 0:
        return bit_rate, str(torrent.get("bit_rate_source") or "torrserver")

    torrent_size = _as_float(torrent.get("torrent_size"))
    duration_seconds = _as_float(torrent.get("duration_seconds"))
    if torrent_size > 0 and duration_seconds >= 300:
        calculated_bit_rate = torrent_size * 8 / duration_seconds
        if 500_000 <= calculated_bit_rate <= 200_000_000:
            return calculated_bit_rate, "size_and_duration"

    title = f"{torrent.get('title', '')} {torrent.get('name', '')}".casefold()
    size_gib = torrent_size / (1024**3)
    if "2160p" in title or "4k" in title:
        if size_gib >= 40:
            return 40_000_000.0, "auto_4k_large"
        if size_gib >= 20:
            return 25_000_000.0, "auto_4k_medium"
        return 16_000_000.0, "auto_4k_compact"
    if "1080p" in title:
        if size_gib >= 20:
            return 20_000_000.0, "auto_1080p_large"
        if size_gib >= 8:
            return 12_000_000.0, "auto_1080p_medium"
        return 8_000_000.0, "auto_1080p_compact"
    if "720p" in title:
        return 6_000_000.0, "auto_720p"
    return float(DEFAULT_BIT_RATE_BPS), "fallback_8_mbps"


@dataclass(frozen=True, slots=True)
class StreamHealth:
    """One explainable streaming-health assessment."""

    state: str
    score: int | None
    reason: str
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _PendingDowngrade:
    """A worse state waiting for its configured confirmation delay."""

    state: str
    since: float


def stream_health_icon(state: str) -> str:
    """Return the icon associated with a streaming-health state."""
    return STREAM_HEALTH_ICONS.get(state, "mdi:traffic-light")


def evaluate_stream_health(
    torrent: Mapping[str, Any] | None,
    stable_margin_percent: float = 0,
    preload_margin_percent: float = 10,
    low_buffer_seconds: float = 15,
    protected_buffer_seconds: float = 60,
    *,
    use_stabilized_state: bool = True,
) -> StreamHealth:
    """Estimate health primarily from playable data ahead of the reader."""
    if torrent is None:
        return StreamHealth(
            state="idle",
            score=None,
            reason="no_active_torrent",
            attributes={"estimated": True, "reason": "no_active_torrent"},
        )

    status = _as_int(torrent.get("stat"))
    if status in {0, 1}:
        return StreamHealth(
            state="unknown",
            score=None,
            reason="torrent_starting",
            attributes={
                "estimated": True,
                "reason": "torrent_starting",
                "torrent_status": status,
            },
        )

    seeders = _as_int(torrent.get("connected_seeders"))
    active_peers = _as_int(torrent.get("active_peers"))
    total_peers = _as_int(torrent.get("total_peers"))
    instant_speed = _as_float(
        torrent.get("instant_download_speed", torrent.get("download_speed"))
    )
    average_value = torrent.get("average_download_speed")
    average_speed = _optional_float(average_value)
    download_speed = average_speed if average_speed is not None else instant_speed
    speed_source = str(
        torrent.get("average_speed_source")
        or ("instantaneous" if average_speed is None else "rolling_average")
    )

    loaded_bytes = _as_int(torrent.get("loaded_size"))
    torrent_size = _as_int(torrent.get("torrent_size"))
    preloaded_bytes = _as_int(torrent.get("preloaded_bytes"))
    bit_rate_bps, bit_rate_source = _bit_rate(torrent)
    required_speed = bit_rate_bps / 8
    speed_ratio = download_speed / required_speed

    stable_margin_percent = max(float(stable_margin_percent), 0)
    preload_margin_percent = max(
        float(preload_margin_percent), stable_margin_percent
    )
    low_buffer_seconds = max(float(low_buffer_seconds), EMERGENCY_BUFFER_SECONDS)
    protected_buffer_seconds = max(
        float(protected_buffer_seconds), low_buffer_seconds
    )
    stable_ratio = 1 + stable_margin_percent / 100
    preload_ratio = 1 + preload_margin_percent / 100
    minimum_stable_speed = required_speed * stable_ratio
    minimum_preload_speed = required_speed * preload_ratio

    reader_buffer_value = torrent.get("buffer_ahead_bytes")
    if reader_buffer_value is not None:
        buffer_ahead_bytes = _as_float(reader_buffer_value)
        buffer_source = "reader_ahead"
    elif preloaded_bytes > 0:
        buffer_ahead_bytes = float(preloaded_bytes)
        buffer_source = "preloaded_fallback"
    else:
        buffer_ahead_bytes = None
        buffer_source = "unavailable"
    buffer_seconds = (
        buffer_ahead_bytes / required_speed
        if buffer_ahead_bytes is not None and required_speed > 0
        else None
    )
    trend_bytes_per_second = _optional_float(
        torrent.get("buffer_trend_bytes_per_second")
    )
    trend_ratio = (
        trend_bytes_per_second / required_speed
        if trend_bytes_per_second is not None and required_speed > 0
        else None
    )
    trend_seconds_per_minute = (
        trend_ratio * 60 if trend_ratio is not None else None
    )
    cache_full = bool(torrent.get("cache_full"))

    if cache_full:
        buffer_mode = "full"
    elif buffer_seconds is None:
        buffer_mode = "unknown"
    elif trend_ratio is None:
        buffer_mode = "measuring"
    elif trend_ratio > BUFFER_TREND_TOLERANCE_RATIO:
        buffer_mode = "preloading"
    elif trend_ratio < -BUFFER_TREND_TOLERANCE_RATIO:
        buffer_mode = "draining"
    elif buffer_seconds < low_buffer_seconds and speed_ratio >= stable_ratio:
        buffer_mode = "recovering"
    else:
        buffer_mode = "stable"

    fully_loaded = torrent_size > 0 and loaded_bytes >= torrent_size
    loaded_percent = (
        min(loaded_bytes / torrent_size * 100, 100.0) if torrent_size else 0.0
    )
    has_sources = seeders > 0 or active_peers > 0 or download_speed >= 1024
    measuring = speed_source == "measuring" and buffer_seconds is None

    if fully_loaded:
        state = "protected"
        reason = "fully_loaded"
    elif cache_full:
        state = "protected"
        reason = "cache_full"
    elif buffer_seconds is not None and buffer_seconds >= protected_buffer_seconds:
        state = "protected"
        reason = "protected_buffer"
    elif measuring:
        state = "measuring"
        reason = "collecting_speed_samples"
    elif not has_sources and (
        buffer_seconds is None or buffer_seconds < low_buffer_seconds
    ):
        state = "insufficient"
        reason = "no_sources"
    elif buffer_seconds is not None:
        if buffer_seconds < low_buffer_seconds and (
            speed_ratio < stable_ratio
            or (
                trend_ratio is not None
                and trend_ratio < -BUFFER_TREND_TOLERANCE_RATIO
            )
        ):
            state = "insufficient"
            reason = "low_buffer_and_insufficient_speed"
        else:
            state = "stable"
            reason = (
                "low_buffer_recovering"
                if buffer_seconds < low_buffer_seconds
                else "buffer_sufficient"
            )
    elif speed_ratio >= preload_ratio:
        state = "protected"
        reason = "above_preload_margin_without_buffer"
    elif speed_ratio >= stable_ratio:
        state = "stable"
        reason = "speed_sustainable_without_buffer"
    else:
        state = "insufficient"
        reason = "speed_insufficient_without_buffer"

    if state == "protected":
        score: int | None = 100
    elif state == "stable":
        if buffer_seconds is not None:
            score = min(
                max(round(50 + 49 * buffer_seconds / protected_buffer_seconds), 50),
                99,
            )
        else:
            score = min(max(round(speed_ratio / preload_ratio * 100), 50), 99)
    elif state == "insufficient":
        score = min(max(round(speed_ratio / max(stable_ratio, 0.01) * 49), 0), 49)
    else:
        score = None

    attributes: dict[str, Any] = {
        "estimated": True,
        "score": score,
        "reason": reason,
        "torrent_status": status,
        "connected_seeders": seeders,
        "active_peers": active_peers,
        "total_peers": total_peers,
        "download_speed_mbps": round(download_speed * 8 / 1_000_000, 2),
        "instant_download_speed_mbps": round(instant_speed * 8 / 1_000_000, 2),
        "average_download_speed_mbps": (
            round(average_speed * 8 / 1_000_000, 2)
            if average_speed is not None
            else None
        ),
        "speed_source": speed_source,
        "average_window_seconds": torrent.get("average_window_seconds"),
        "speed_sample_count": torrent.get("speed_sample_count"),
        "required_download_speed_mbps": round(bit_rate_bps / 1_000_000, 2),
        "minimum_stable_speed_mbps": round(
            minimum_stable_speed * 8 / 1_000_000, 2
        ),
        "minimum_preload_speed_mbps": round(
            minimum_preload_speed * 8 / 1_000_000, 2
        ),
        "speed_ratio": round(speed_ratio, 2),
        "speed_margin_percent": round((speed_ratio - 1) * 100, 1),
        "stable_margin_percent": stable_margin_percent,
        "preload_margin_percent": preload_margin_percent,
        "buffer_ahead_bytes": (
            round(buffer_ahead_bytes) if buffer_ahead_bytes is not None else None
        ),
        "buffer_seconds": (
            round(buffer_seconds, 1) if buffer_seconds is not None else None
        ),
        "buffer_source": buffer_source,
        "buffer_mode": buffer_mode,
        "buffer_trend_seconds_per_minute": (
            round(trend_seconds_per_minute, 1)
            if trend_seconds_per_minute is not None
            else None
        ),
        "buffer_sample_count": torrent.get("buffer_sample_count"),
        "low_buffer_seconds": low_buffer_seconds,
        "protected_buffer_seconds": protected_buffer_seconds,
        "cache_fill_percent": torrent.get("cache_fill_percent"),
        "cache_full": cache_full,
        "cache_full_threshold": torrent.get("cache_full_threshold"),
        "loaded_percent": round(loaded_percent, 1),
        "bit_rate_mbps": round(bit_rate_bps / 1_000_000, 2),
        "bit_rate_source": bit_rate_source,
    }

    candidate_state = state
    candidate_reason = reason
    if use_stabilized_state and torrent.get("stabilized_stream_health_state"):
        state = str(torrent["stabilized_stream_health_state"])
        reason = str(torrent.get("stabilized_stream_health_reason") or reason)
        attributes.update(
            {
                "reason": reason,
                "candidate_state": candidate_state,
                "candidate_reason": candidate_reason,
                "transition_pending_seconds": torrent.get(
                    "stream_health_pending_seconds"
                ),
            }
        )
        if state == "protected":
            score = 100
        elif state == "stable" and score is not None:
            score = max(score, 50)
        attributes["score"] = score

    return StreamHealth(state=state, score=score, reason=reason, attributes=attributes)


class StreamHealthTracker:
    """Apply downgrade hysteresis once per coordinator update."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._pending: dict[str, _PendingDowngrade] = {}

    def apply(
        self,
        torrents: tuple[dict[str, Any], ...],
        *,
        now: float,
        stable_margin_percent: float,
        preload_margin_percent: float,
        low_buffer_seconds: float,
        protected_buffer_seconds: float,
        downgrade_delay_seconds: float,
    ) -> None:
        """Annotate streams with a stable state and transition diagnostics."""
        active_keys: set[str] = set()
        delay = max(float(downgrade_delay_seconds), 0)

        for torrent in torrents:
            key = _stream_key(torrent)
            active_keys.add(key)
            assessment = evaluate_stream_health(
                torrent,
                stable_margin_percent=stable_margin_percent,
                preload_margin_percent=preload_margin_percent,
                low_buffer_seconds=low_buffer_seconds,
                protected_buffer_seconds=protected_buffer_seconds,
                use_stabilized_state=False,
            )
            candidate = assessment.state
            current = self._states.get(key)
            pending_seconds: float | None = None
            emergency = (
                assessment.attributes.get("buffer_seconds") is not None
                and float(assessment.attributes["buffer_seconds"])
                <= EMERGENCY_BUFFER_SECONDS
            ) or assessment.reason == "no_sources"

            if current is None or current not in _STATE_PRIORITY:
                state = candidate
                self._pending.pop(key, None)
            elif (
                _STATE_PRIORITY[candidate] > _STATE_PRIORITY[current]
                and not emergency
                and delay > 0
            ):
                pending = self._pending.get(key)
                if pending is None or pending.state != candidate:
                    self._pending[key] = _PendingDowngrade(candidate, now)
                    state = current
                    pending_seconds = delay
                else:
                    elapsed = max(now - pending.since, 0)
                    if elapsed >= delay:
                        state = candidate
                        self._pending.pop(key, None)
                    else:
                        state = current
                        pending_seconds = delay - elapsed
            else:
                state = candidate
                self._pending.pop(key, None)

            self._states[key] = state
            torrent["stabilized_stream_health_state"] = state
            torrent["stabilized_stream_health_reason"] = (
                "downgrade_pending"
                if pending_seconds is not None
                else assessment.reason
            )
            torrent["stream_health_candidate_state"] = candidate
            torrent["stream_health_candidate_reason"] = assessment.reason
            torrent["stream_health_pending_seconds"] = (
                round(pending_seconds, 1) if pending_seconds is not None else None
            )
            torrent["buffer_seconds"] = assessment.attributes.get("buffer_seconds")
            torrent["buffer_mode"] = assessment.attributes.get("buffer_mode")
            torrent["buffer_trend_seconds_per_minute"] = assessment.attributes.get(
                "buffer_trend_seconds_per_minute"
            )

        for stale_key in set(self._states) - active_keys:
            self._states.pop(stale_key, None)
            self._pending.pop(stale_key, None)


def evaluate_streams_health(
    torrents: Iterable[Mapping[str, Any]],
    stable_margin_percent: float = 0,
    preload_margin_percent: float = 10,
    low_buffer_seconds: float = 15,
    protected_buffer_seconds: float = 60,
) -> StreamHealth:
    """Return the worst stabilized health across active TorrServer streams."""
    assessments = [
        evaluate_stream_health(
            torrent,
            stable_margin_percent=stable_margin_percent,
            preload_margin_percent=preload_margin_percent,
            low_buffer_seconds=low_buffer_seconds,
            protected_buffer_seconds=protected_buffer_seconds,
        )
        for torrent in torrents
    ]
    if not assessments:
        return StreamHealth(
            state="idle",
            score=None,
            reason="no_active_torrent",
            attributes={
                "estimated": True,
                "reason": "no_active_torrent",
                "stream_count": 0,
                "protected_streams": 0,
                "stable_streams": 0,
                "insufficient_streams": 0,
                "measuring_streams": 0,
                "unknown_streams": 0,
            },
        )

    worst = max(assessments, key=lambda item: _STATE_PRIORITY[item.state])
    counts = Counter(item.state for item in assessments)
    scored = [item.score for item in assessments if item.score is not None]
    attributes = {
        "estimated": True,
        "reason": worst.reason,
        "stream_count": len(assessments),
        "protected_streams": counts["protected"],
        "stable_streams": counts["stable"],
        "insufficient_streams": counts["insufficient"],
        "measuring_streams": counts["measuring"],
        "unknown_streams": counts["unknown"],
        "worst_score": min(scored) if scored else None,
        "worst_reason": worst.reason,
    }
    if len(assessments) == 1:
        attributes.update(worst.attributes)
        attributes["stream_count"] = 1
        attributes["worst_score"] = worst.score
        attributes["worst_reason"] = worst.reason

    return StreamHealth(
        state=worst.state,
        score=min(scored) if scored else None,
        reason=worst.reason,
        attributes=attributes,
    )
