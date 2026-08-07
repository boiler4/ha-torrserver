"""Estimated streaming health for an active TorrServer torrent."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

DEFAULT_BIT_RATE_BPS: Final = 8_000_000
STREAM_HEALTH_OPTIONS: Final = ["idle", "red", "yellow", "green", "unknown"]
STREAM_HEALTH_ICONS: Final = {
    "idle": "mdi:minus-circle-outline",
    "red": "mdi:alert-circle",
    "yellow": "mdi:alert",
    "green": "mdi:check-circle",
    "unknown": "mdi:help-circle-outline",
}
_STATE_PRIORITY: Final = {"green": 0, "unknown": 1, "yellow": 2, "red": 3}


def _as_float(value: Any) -> float:
    """Convert a TorrServer value to a non-negative float."""
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    """Convert a TorrServer value to a non-negative integer."""
    return round(_as_float(value))


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


def stream_health_icon(state: str) -> str:
    """Return the icon associated with a streaming-health state."""
    return STREAM_HEALTH_ICONS.get(state, "mdi:traffic-light")


def evaluate_stream_health(
    torrent: Mapping[str, Any] | None,
    yellow_margin_percent: float = 10,
    green_margin_percent: float = 50,
) -> StreamHealth:
    """Estimate stream health without claiming knowledge of the player buffer."""
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
    download_speed = _as_float(torrent.get("download_speed"))
    preloaded_bytes = _as_int(torrent.get("preloaded_bytes"))
    loaded_bytes = _as_int(torrent.get("loaded_size"))
    torrent_size = _as_int(torrent.get("torrent_size"))

    bit_rate_bps, bit_rate_source = _bit_rate(torrent)
    required_speed = bit_rate_bps / 8
    speed_ratio = download_speed / required_speed
    estimated_preload_seconds = preloaded_bytes / required_speed
    loaded_percent = (
        min(loaded_bytes / torrent_size * 100, 100.0) if torrent_size else 0.0
    )

    yellow_margin_percent = max(float(yellow_margin_percent), 0)
    green_margin_percent = max(float(green_margin_percent), yellow_margin_percent)
    yellow_ratio = 1 + yellow_margin_percent / 100
    green_ratio = 1 + green_margin_percent / 100
    minimum_yellow_speed = required_speed * yellow_ratio
    minimum_green_speed = required_speed * green_ratio
    fully_loaded = torrent_size > 0 and loaded_bytes >= torrent_size
    has_sources = seeders > 0 or active_peers > 0 or download_speed >= 1024
    if fully_loaded:
        state = "green"
        reason = "fully_loaded"
        score = 100
    elif not has_sources:
        state = "red"
        reason = "no_sources"
        score = 0
    elif download_speed >= minimum_green_speed:
        state = "green"
        reason = "above_green_margin"
        score = 100
    elif download_speed >= minimum_yellow_speed:
        state = "yellow"
        reason = "above_yellow_margin"
        score = min(round(speed_ratio / green_ratio * 100), 99)
    else:
        state = "red"
        reason = "below_yellow_margin"
        score = min(round(speed_ratio / green_ratio * 100), 99)

    return StreamHealth(
        state=state,
        score=score,
        reason=reason,
        attributes={
            "estimated": True,
            "score": score,
            "reason": reason,
            "torrent_status": status,
            "connected_seeders": seeders,
            "active_peers": active_peers,
            "total_peers": total_peers,
            "download_speed_mbps": round(download_speed * 8 / 1_000_000, 2),
            "required_download_speed_mbps": round(bit_rate_bps / 1_000_000, 2),
            "minimum_yellow_speed_mbps": round(
                minimum_yellow_speed * 8 / 1_000_000, 2
            ),
            "minimum_green_speed_mbps": round(
                minimum_green_speed * 8 / 1_000_000, 2
            ),
            "speed_ratio": round(speed_ratio, 2),
            "speed_margin_percent": round((speed_ratio - 1) * 100, 1),
            "yellow_margin_percent": yellow_margin_percent,
            "green_margin_percent": green_margin_percent,
            "preloaded_bytes": preloaded_bytes,
            "estimated_preload_seconds": round(estimated_preload_seconds, 1),
            "loaded_percent": round(loaded_percent, 1),
            "bit_rate_mbps": round(bit_rate_bps / 1_000_000, 2),
            "bit_rate_source": bit_rate_source,
        },
    )


def evaluate_streams_health(
    torrents: Iterable[Mapping[str, Any]],
    yellow_margin_percent: float = 10,
    green_margin_percent: float = 50,
) -> StreamHealth:
    """Return the worst health across every active TorrServer stream."""
    assessments = [
        evaluate_stream_health(
            torrent,
            yellow_margin_percent=yellow_margin_percent,
            green_margin_percent=green_margin_percent,
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
                "green_streams": 0,
                "yellow_streams": 0,
                "red_streams": 0,
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
        "green_streams": counts["green"],
        "yellow_streams": counts["yellow"],
        "red_streams": counts["red"],
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
