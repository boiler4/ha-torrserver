"""Privacy-safe structured diagnostics for streaming health."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .stream_health import evaluate_stream_health


def stream_diagnostic_sample(
    torrent: Mapping[str, Any],
    *,
    sequence: int,
    index: int,
    total: int,
    stable_margin_percent: float,
    preload_margin_percent: float,
    low_buffer_seconds: float,
    protected_buffer_seconds: float,
    ffprobe_status: str,
    ffprobe_failures: int,
    ffprobe_last_error: str | None,
    ffprobe_retry_seconds: float | None,
) -> dict[str, Any]:
    """Build one privacy-safe, machine-readable health sample."""
    health = evaluate_stream_health(
        torrent,
        stable_margin_percent=stable_margin_percent,
        preload_margin_percent=preload_margin_percent,
        low_buffer_seconds=low_buffer_seconds,
        protected_buffer_seconds=protected_buffer_seconds,
    )
    attributes = health.attributes
    return {
        "event": "stream_health_sample",
        "sequence": sequence,
        "stream_index": index,
        "stream_count": total,
        "health": health.state,
        "health_candidate": torrent.get("stream_health_candidate_state"),
        "health_reason": health.reason,
        "health_score": health.score,
        "health_pending_seconds": torrent.get("stream_health_pending_seconds"),
        "forecast": torrent.get("stream_forecast_state"),
        "forecast_reason": torrent.get("stream_forecast_reason"),
        "interruption_risk": torrent.get("stream_interruption_risk"),
        "interruption_eta_seconds": torrent.get("stream_interruption_eta_seconds"),
        "reader_v2_condition": torrent.get("shadow_condition"),
        "reader_v2_candidate_condition": torrent.get("shadow_candidate_condition"),
        "reader_v2_phase": torrent.get("shadow_phase"),
        "reader_v2_health": torrent.get("shadow_health_state"),
        "reader_v2_buffer_mode": torrent.get("shadow_buffer_mode"),
        "reader_v2_forecast": torrent.get("shadow_forecast_state"),
        "reader_v2_interruption_risk": torrent.get("shadow_interruption_risk"),
        "reader_v2_candidate_risk": torrent.get("shadow_candidate_risk"),
        "reader_v2_risk_transition_pending_seconds": torrent.get(
            "shadow_risk_transition_pending_seconds"
        ),
        "reader_v2_eta_seconds": torrent.get("shadow_eta_seconds"),
        "reader_v2_eta_source": torrent.get("shadow_eta_source"),
        "reader_v2_reason": torrent.get("shadow_reason"),
        "reader_v2_candidate_reason": torrent.get("shadow_candidate_reason"),
        "reader_v2_confidence": torrent.get("shadow_confidence"),
        "reader_v2_transition_pending_seconds": torrent.get(
            "shadow_transition_pending_seconds"
        ),
        "reader_v2_long_speed_ratio": torrent.get("shadow_long_speed_ratio"),
        "reader_v2_short_speed_ratio": torrent.get("shadow_short_speed_ratio"),
        "reader_v2_buffer_trend_seconds_per_minute": torrent.get(
            "shadow_buffer_trend_seconds_per_minute"
        ),
        "reader_v2_remaining_file_cached": torrent.get("shadow_remaining_file_cached"),
        "reader_v2_health_differs": (
            torrent.get("shadow_health_state") is not None
            and torrent.get("shadow_health_state") != health.state
        ),
        "reader_v2_forecast_differs": (
            torrent.get("shadow_forecast_state") is not None
            and torrent.get("shadow_forecast_state")
            != torrent.get("stream_forecast_state")
        ),
        "reader_v2_risk_differs": (
            torrent.get("shadow_interruption_risk") is not None
            and bool(torrent.get("shadow_interruption_risk"))
            != bool(torrent.get("stream_interruption_risk"))
        ),
        "buffer_seconds": attributes.get("buffer_seconds"),
        "buffer_mode": attributes.get("buffer_mode"),
        "buffer_source": attributes.get("buffer_source"),
        "buffer_trend_seconds_per_minute": attributes.get(
            "buffer_trend_seconds_per_minute"
        ),
        "bit_rate_mbps": attributes.get("bit_rate_mbps"),
        "bit_rate_source": attributes.get("bit_rate_source"),
        "bit_rate_estimated": attributes.get("bit_rate_estimated"),
        "download_speed_mbps": attributes.get("download_speed_mbps"),
        "instant_download_speed_mbps": attributes.get("instant_download_speed_mbps"),
        "average_download_speed_mbps": attributes.get("average_download_speed_mbps"),
        "speed_source": attributes.get("speed_source"),
        "speed_ratio": attributes.get("speed_ratio"),
        "speed_margin_percent": attributes.get("speed_margin_percent"),
        "speed_sample_count": torrent.get("speed_sample_count"),
        "buffer_sample_count": torrent.get("buffer_sample_count"),
        "cache_fill_percent": attributes.get("cache_fill_percent"),
        "cache_full": attributes.get("cache_full"),
        "connected_seeders": attributes.get("connected_seeders"),
        "active_peers": attributes.get("active_peers"),
        "session_duration_seconds": torrent.get("stream_session_duration_seconds"),
        "session_minimum_buffer_seconds": torrent.get(
            "stream_session_minimum_buffer_seconds"
        ),
        "session_average_speed_mbps": torrent.get("stream_session_average_speed_mbps"),
        "session_insufficient_seconds": torrent.get(
            "stream_session_insufficient_seconds"
        ),
        "session_risk_events": torrent.get("stream_session_risk_events"),
        "ffprobe_status": torrent.get("ffprobe_status", ffprobe_status),
        "ffprobe_failures": torrent.get("ffprobe_failure_count", ffprobe_failures),
        "ffprobe_last_error": torrent.get("ffprobe_last_error", ffprobe_last_error),
        "ffprobe_retry_seconds": torrent.get(
            "ffprobe_retry_seconds", ffprobe_retry_seconds
        ),
    }
