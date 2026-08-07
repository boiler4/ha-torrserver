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
    """Return a bit rate and whether TorrServer or the fallback supplied it."""
    bit_rate = _as_float(torrent.get("bit_rate"))
    if bit_rate > 0:
        return bit_rate, "torrserver"
    return float(DEFAULT_BIT_RATE_BPS), "fallback_8_mbps"


def _speed_points(ratio: float) -> int:
    if ratio >= 1.5:
        return 35
    if ratio >= 1.0:
        return 30
    if ratio >= 0.75:
        return 20
    if ratio >= 0.25:
        return 10
    if ratio > 0:
        return 5
    return 0


def _preload_points(seconds: float) -> int:
    if seconds >= 300:
        return 20
    if seconds >= 120:
        return 15
    if seconds >= 30:
        return 8
    if seconds > 0:
        return 3
    return 0


def _seeder_points(seeders: int) -> int:
    if seeders >= 4:
        return 20
    if seeders == 3:
        return 18
    if seeders == 2:
        return 14
    if seeders == 1:
        return 8
    return 0


def _peer_points(peers: int) -> int:
    if peers >= 5:
        return 20
    if peers == 4:
        return 17
    if peers == 3:
        return 14
    if peers == 2:
        return 10
    if peers == 1:
        return 5
    return 0


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

    loaded_points = 5 if loaded_percent >= 50 else 3 if loaded_percent >= 10 else 1
    if loaded_percent == 0:
        loaded_points = 0

    score = min(
        _seeder_points(seeders)
        + _peer_points(active_peers)
        + _speed_points(speed_ratio)
        + _preload_points(estimated_preload_seconds)
        + loaded_points,
        100,
    )

    has_sources = seeders > 0 or active_peers > 0 or download_speed >= 1024
    if not has_sources:
        if estimated_preload_seconds >= 120:
            state = "yellow"
            reason = "cached_but_no_sources"
        else:
            state = "red"
            reason = "no_sources"
    elif score >= 60:
        state = "green"
        if speed_ratio >= 1:
            reason = "download_faster_than_stream"
        elif seeders >= 4 and estimated_preload_seconds >= 120:
            reason = "strong_swarm_and_preload"
        else:
            reason = "healthy_margin"
    elif score >= 30:
        state = "yellow"
        reason = "limited_margin"
    else:
        state = "red"
        reason = "insufficient_margin"

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
            "download_speed_bps": round(download_speed, 2),
            "required_download_speed_bps": round(required_speed, 2),
            "speed_ratio": round(speed_ratio, 2),
            "preloaded_bytes": preloaded_bytes,
            "estimated_preload_seconds": round(estimated_preload_seconds, 1),
            "loaded_percent": round(loaded_percent, 1),
            "bit_rate_bps": round(bit_rate_bps),
            "bit_rate_source": bit_rate_source,
        },
    )


def evaluate_streams_health(
    torrents: Iterable[Mapping[str, Any]],
) -> StreamHealth:
    """Return the worst health across every active TorrServer stream."""
    assessments = [evaluate_stream_health(torrent) for torrent in torrents]
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
