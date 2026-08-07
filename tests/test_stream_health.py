"""Tests for the explainable streaming-health estimate."""

from __future__ import annotations

from custom_components.torrserver.stream_health import evaluate_stream_health


def test_stream_health_is_idle_without_an_active_torrent():
    health = evaluate_stream_health(None)

    assert health.state == "idle"
    assert health.score is None
    assert health.reason == "no_active_torrent"


def test_stream_health_is_unknown_while_torrent_is_starting():
    health = evaluate_stream_health({"stat": 1})

    assert health.state == "unknown"
    assert health.reason == "torrent_starting"


def test_stream_health_is_green_with_strong_swarm_and_preload():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "connected_seeders": 19,
            "active_peers": 24,
            "total_peers": 113,
            "preloaded_bytes": 1_073_106_082,
            "loaded_size": 1_077_234_850,
            "torrent_size": 3_593_882_786,
        }
    )

    assert health.state == "green"
    assert health.score == 63
    assert health.reason == "strong_swarm_and_preload"
    assert health.attributes["bit_rate_source"] == "fallback_8_mbps"


def test_stream_health_is_green_when_download_exceeds_stream_rate():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "connected_seeders": 3,
            "active_peers": 4,
            "download_speed": 1_600_000,
        }
    )

    assert health.state == "green"
    assert health.reason == "download_faster_than_stream"
    assert health.attributes["speed_ratio"] == 1.6


def test_stream_health_is_yellow_with_limited_margin():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "connected_seeders": 1,
            "active_peers": 1,
            "download_speed": 500_000,
            "preloaded_bytes": 64_000_000,
        }
    )

    assert health.state == "yellow"
    assert health.reason == "limited_margin"


def test_stream_health_is_red_without_sources_or_preload():
    health = evaluate_stream_health({"stat": 3})

    assert health.state == "red"
    assert health.reason == "no_sources"


def test_stream_health_is_yellow_when_cached_but_sources_are_gone():
    health = evaluate_stream_health(
        {"stat": 3, "preloaded_bytes": 200_000_000}
    )

    assert health.state == "yellow"
    assert health.reason == "cached_but_no_sources"


def test_stream_health_uses_torrserver_bit_rate_when_available():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "connected_seeders": 4,
            "active_peers": 5,
            "download_speed": 2_200_000,
            "bit_rate": "16000000",
        }
    )

    assert health.attributes["bit_rate_source"] == "torrserver"
    assert health.attributes["required_download_speed_bps"] == 2_000_000
    assert health.attributes["speed_ratio"] == 1.1
