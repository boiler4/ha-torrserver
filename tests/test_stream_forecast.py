"""Tests for streaming autonomy, forecast, and session summaries."""

from custom_components.torrserver.stream_forecast import (
    StreamForecastTracker,
    evaluate_stream_forecast,
    evaluate_streams_forecast,
    stream_forecast_icon,
)


def _stream(
    *,
    buffer_seconds: float = 60,
    trend_seconds_per_minute: float = 0,
    speed: int = 1_000_000,
    bit_rate: int = 8_000_000,
) -> dict:
    required_bytes_per_second = bit_rate / 8
    return {
        "hash": "abc",
        "stat": 3,
        "connected_seeders": 2,
        "active_peers": 2,
        "download_speed": speed,
        "average_download_speed": speed,
        "average_speed_source": "rolling_average",
        "bit_rate": bit_rate,
        "buffer_ahead_bytes": buffer_seconds * required_bytes_per_second,
        "buffer_trend_bytes_per_second": (
            trend_seconds_per_minute / 60 * required_bytes_per_second
        ),
        "stabilized_stream_health_state": "stable",
        "stabilized_stream_health_reason": "buffer_sufficient",
    }


def _apply(
    tracker: StreamForecastTracker,
    torrent: dict,
    *,
    now: float,
    confirmation: float = 15,
) -> None:
    tracker.apply(
        (torrent,),
        now=now,
        risk_horizon_seconds=60,
        confirmation_seconds=confirmation,
        stable_margin_percent=0,
        preload_margin_percent=10,
        low_buffer_seconds=15,
        protected_buffer_seconds=60,
    )


def test_sustainable_buffer_has_no_invented_interruption_eta():
    forecast = evaluate_stream_forecast(
        _stream(buffer_seconds=40, trend_seconds_per_minute=5)
    )

    assert forecast.state == "sustainable"
    assert forecast.risk is False
    assert forecast.eta_seconds is None


def test_depleting_buffer_exposes_time_to_empty():
    forecast = evaluate_stream_forecast(
        _stream(buffer_seconds=30, trend_seconds_per_minute=-30)
    )

    assert forecast.state == "depleting"
    assert forecast.eta_seconds == 60
    assert forecast.attributes["candidate_risk"] is True


def test_risk_requires_configured_confirmation_time():
    tracker = StreamForecastTracker()
    first = _stream(buffer_seconds=20, trend_seconds_per_minute=-30)
    _apply(tracker, first, now=0)
    assert first["stream_interruption_risk"] is False
    assert first["stream_risk_confirmation_pending_seconds"] == 15

    second = _stream(buffer_seconds=15, trend_seconds_per_minute=-30)
    _apply(tracker, second, now=10)
    assert second["stream_interruption_risk"] is False
    assert second["stream_risk_confirmation_pending_seconds"] == 5

    third = _stream(buffer_seconds=10, trend_seconds_per_minute=-30)
    _apply(tracker, third, now=15)
    assert third["stream_interruption_risk"] is True
    assert third["stream_forecast_state"] == "at_risk"
    assert third["stream_session_risk_events"] == 1


def test_emergency_buffer_activates_risk_immediately():
    tracker = StreamForecastTracker()
    torrent = _stream(buffer_seconds=4, trend_seconds_per_minute=-10)

    _apply(tracker, torrent, now=0, confirmation=30)

    assert torrent["stream_interruption_risk"] is True
    assert torrent["stream_risk_confirmation_pending_seconds"] is None


def test_session_summary_accumulates_minimum_average_and_insufficient_time():
    tracker = StreamForecastTracker()
    first = _stream(buffer_seconds=50, speed=2_000_000)
    first["stabilized_stream_health_state"] = "insufficient"
    _apply(tracker, first, now=0)

    second = _stream(buffer_seconds=30, speed=1_000_000)
    second["stabilized_stream_health_state"] = "stable"
    _apply(tracker, second, now=10)

    assert second["stream_session_duration_seconds"] == 10
    assert second["stream_session_minimum_buffer_seconds"] == 30
    assert second["stream_session_average_speed_mbps"] == 12
    assert second["stream_session_insufficient_seconds"] == 10


def test_multiple_streams_return_worst_forecast_and_minimum_eta():
    safe = _stream(buffer_seconds=80, trend_seconds_per_minute=10)
    safe["hash"] = "safe"
    risk = _stream(buffer_seconds=10, trend_seconds_per_minute=-20)
    risk["hash"] = "risk"
    risk["stream_interruption_risk"] = True
    risk["stream_interruption_eta_seconds"] = 30

    forecast = evaluate_streams_forecast((safe, risk))

    assert forecast.state == "at_risk"
    assert forecast.risk is True
    assert forecast.eta_seconds == 30
    assert forecast.attributes["at_risk_streams"] == 1


def test_forecast_icons_are_state_aware():
    assert stream_forecast_icon("sustainable") == "mdi:play-circle-outline"
    assert stream_forecast_icon("depleting") == "mdi:timer-sand"
    assert stream_forecast_icon("at_risk") == "mdi:progress-alert"
