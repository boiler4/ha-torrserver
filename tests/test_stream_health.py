"""Tests for buffer-first streaming health."""

from __future__ import annotations

from custom_components.torrserver.stream_health import (
    StreamHealthTracker,
    evaluate_stream_health,
    evaluate_streams_health,
    stream_health_icon,
)


def _stream(
    *,
    speed: int = 1_000_000,
    buffer_seconds: float | None = None,
    bit_rate: int = 8_000_000,
) -> dict:
    torrent = {
        "hash": "abc",
        "stat": 3,
        "connected_seeders": 2,
        "active_peers": 3,
        "download_speed": speed,
        "average_download_speed": speed,
        "average_speed_source": "rolling_average",
        "bit_rate": bit_rate,
    }
    if buffer_seconds is not None:
        torrent["buffer_ahead_bytes"] = buffer_seconds * (bit_rate / 8)
    return torrent


def test_stream_health_is_idle_without_an_active_torrent():
    health = evaluate_stream_health(None)

    assert health.state == "idle"
    assert health.reason == "no_active_torrent"


def test_stream_health_is_unknown_while_torrent_is_starting():
    health = evaluate_stream_health({"stat": 1})

    assert health.state == "unknown"
    assert health.reason == "torrent_starting"


def test_full_cache_is_protected_even_when_download_is_paused():
    torrent = _stream(speed=0, buffer_seconds=90)
    torrent["cache_full"] = True
    torrent["average_download_speed"] = None

    health = evaluate_stream_health(torrent)

    assert health.state == "protected"
    assert health.reason == "cache_full"
    assert health.attributes["buffer_mode"] == "full"


def test_large_reader_buffer_overrides_speed_below_nominal_bitrate():
    health = evaluate_stream_health(
        _stream(
            speed=8_340_000,
            buffer_seconds=114,
            bit_rate=71_490_000,
        )
    )

    assert health.state == "protected"
    assert health.reason == "protected_buffer"
    assert health.attributes["speed_margin_percent"] < 0
    assert health.attributes["buffer_seconds"] == 114


def test_sufficient_buffer_is_stable_while_speed_is_below_bitrate():
    health = evaluate_stream_health(_stream(speed=700_000, buffer_seconds=30))

    assert health.state == "stable"
    assert health.reason == "buffer_sufficient"


def test_low_and_draining_buffer_with_insufficient_speed_is_red():
    torrent = _stream(speed=700_000, buffer_seconds=10)
    torrent["buffer_trend_bytes_per_second"] = -200_000

    health = evaluate_stream_health(torrent)

    assert health.state == "insufficient"
    assert health.reason == "low_buffer_and_insufficient_speed"
    assert health.attributes["buffer_mode"] == "draining"


def test_low_buffer_is_stable_when_download_can_recover():
    torrent = _stream(speed=1_100_000, buffer_seconds=10)
    torrent["buffer_trend_bytes_per_second"] = 0

    health = evaluate_stream_health(torrent)

    assert health.state == "stable"
    assert health.reason == "low_buffer_recovering"
    assert health.attributes["buffer_mode"] == "recovering"


def test_speed_margins_are_used_when_reader_buffer_is_unavailable():
    insufficient = evaluate_stream_health(_stream(speed=900_000))
    stable = evaluate_stream_health(_stream(speed=1_000_000))
    protected = evaluate_stream_health(_stream(speed=1_100_000))

    assert insufficient.state == "insufficient"
    assert stable.state == "stable"
    assert protected.state == "protected"
    assert protected.reason == "above_preload_margin_without_buffer"


def test_custom_thresholds_and_margins_are_exposed():
    health = evaluate_stream_health(
        _stream(speed=1_050_000, buffer_seconds=45),
        stable_margin_percent=5,
        preload_margin_percent=20,
        low_buffer_seconds=20,
        protected_buffer_seconds=90,
    )

    assert health.state == "stable"
    assert health.attributes["minimum_stable_speed_mbps"] == 8.4
    assert health.attributes["minimum_preload_speed_mbps"] == 9.6
    assert health.attributes["low_buffer_seconds"] == 20
    assert health.attributes["protected_buffer_seconds"] == 90


def test_buffer_trend_identifies_preloading_mode():
    torrent = _stream(speed=1_300_000, buffer_seconds=30)
    torrent["buffer_trend_bytes_per_second"] = 250_000

    health = evaluate_stream_health(torrent)

    assert health.state == "stable"
    assert health.attributes["buffer_mode"] == "preloading"
    assert health.attributes["buffer_trend_seconds_per_minute"] == 15


def test_completely_loaded_file_is_protected_without_download_speed():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "loaded_size": 10_000_000,
            "torrent_size": 10_000_000,
        }
    )

    assert health.state == "protected"
    assert health.reason == "fully_loaded"


def test_real_torrserver_bitrate_wins_over_title_estimate():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "title": "Large 4K (2160p)",
            "torrent_size": 60 * 1024**3,
            "bit_rate": 18_000_000,
            "connected_seeders": 3,
            "download_speed": 2_500_000,
        }
    )

    assert health.attributes["bit_rate_source"] == "torrserver"
    assert health.attributes["bit_rate_mbps"] == 18


def test_multiple_streams_report_worst_new_state_and_counts():
    protected = _stream(speed=1_200_000, buffer_seconds=90)
    protected["hash"] = "protected"
    stable = _stream(speed=1_000_000, buffer_seconds=30)
    stable["hash"] = "stable"
    insufficient = _stream(speed=500_000, buffer_seconds=10)
    insufficient["hash"] = "insufficient"

    health = evaluate_streams_health((protected, stable, insufficient))

    assert health.state == "insufficient"
    assert health.attributes["protected_streams"] == 1
    assert health.attributes["stable_streams"] == 1
    assert health.attributes["insufficient_streams"] == 1


def test_health_icons_match_semantic_states():
    assert stream_health_icon("insufficient") == "mdi:alert-circle"
    assert stream_health_icon("stable") == "mdi:check-circle-outline"
    assert stream_health_icon("protected") == "mdi:shield-check"
    assert stream_health_icon("measuring") == "mdi:timer-sand"


def test_tracker_delays_non_emergency_downgrades():
    tracker = StreamHealthTracker()
    protected = _stream(buffer_seconds=80)
    tracker.apply(
        (protected,),
        now=0,
        stable_margin_percent=0,
        preload_margin_percent=10,
        low_buffer_seconds=15,
        protected_buffer_seconds=60,
        downgrade_delay_seconds=15,
    )
    assert protected["stabilized_stream_health_state"] == "protected"

    stable = _stream(buffer_seconds=30)
    tracker.apply(
        (stable,),
        now=5,
        stable_margin_percent=0,
        preload_margin_percent=10,
        low_buffer_seconds=15,
        protected_buffer_seconds=60,
        downgrade_delay_seconds=15,
    )
    assert stable["stabilized_stream_health_state"] == "protected"
    assert stable["stabilized_stream_health_reason"] == "downgrade_pending"
    assert stable["stream_health_pending_seconds"] == 15

    stable_later = _stream(buffer_seconds=30)
    tracker.apply(
        (stable_later,),
        now=20,
        stable_margin_percent=0,
        preload_margin_percent=10,
        low_buffer_seconds=15,
        protected_buffer_seconds=60,
        downgrade_delay_seconds=15,
    )
    assert stable_later["stabilized_stream_health_state"] == "stable"


def test_tracker_does_not_delay_emergency_buffer_state():
    tracker = StreamHealthTracker()
    protected = _stream(buffer_seconds=80)
    tracker.apply(
        (protected,),
        now=0,
        stable_margin_percent=0,
        preload_margin_percent=10,
        low_buffer_seconds=15,
        protected_buffer_seconds=60,
        downgrade_delay_seconds=30,
    )
    emergency = _stream(speed=100_000, buffer_seconds=4)
    tracker.apply(
        (emergency,),
        now=5,
        stable_margin_percent=0,
        preload_margin_percent=10,
        low_buffer_seconds=15,
        protected_buffer_seconds=60,
        downgrade_delay_seconds=30,
    )

    assert emergency["stabilized_stream_health_state"] == "insufficient"
    assert emergency["stream_health_pending_seconds"] is None
