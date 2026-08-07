"""Tests for the explainable streaming-health estimate."""

from __future__ import annotations

from custom_components.torrserver.stream_health import (
    evaluate_stream_health,
    evaluate_streams_health,
    stream_health_icon,
)


def test_stream_health_is_idle_without_an_active_torrent():
    health = evaluate_stream_health(None)

    assert health.state == "idle"
    assert health.score is None
    assert health.reason == "no_active_torrent"


def test_stream_health_is_unknown_while_torrent_is_starting():
    health = evaluate_stream_health({"stat": 1})

    assert health.state == "unknown"
    assert health.reason == "torrent_starting"


def test_strong_swarm_and_preload_cannot_override_insufficient_speed():
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

    assert health.state == "red"
    assert health.reason == "below_yellow_margin"
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
    assert health.reason == "above_green_margin"
    assert health.attributes["speed_ratio"] == 1.6


def test_stream_health_is_yellow_between_configured_margins():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "connected_seeders": 1,
            "active_peers": 1,
            "download_speed": 1_200_000,
            "preloaded_bytes": 64_000_000,
        }
    )

    assert health.state == "yellow"
    assert health.reason == "above_yellow_margin"


def test_stream_health_is_red_without_sources_or_preload():
    health = evaluate_stream_health({"stat": 3})

    assert health.state == "red"
    assert health.reason == "no_sources"


def test_cached_data_cannot_override_missing_sources():
    health = evaluate_stream_health(
        {"stat": 3, "preloaded_bytes": 200_000_000}
    )

    assert health.state == "red"
    assert health.reason == "no_sources"


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
    assert health.attributes["download_speed_mbps"] == 17.6
    assert health.attributes["required_download_speed_mbps"] == 16.0
    assert health.attributes["speed_ratio"] == 1.1
    assert health.state == "yellow"
    assert health.attributes["minimum_yellow_speed_mbps"] == 17.6
    assert health.attributes["minimum_green_speed_mbps"] == 24.0


def test_stream_health_respects_custom_speed_margins():
    yellow = evaluate_stream_health(
        {
            "stat": 3,
            "connected_seeders": 2,
            "download_speed": 1_100_000,
        },
        yellow_margin_percent=5,
        green_margin_percent=20,
    )
    green = evaluate_stream_health(
        {
            "stat": 3,
            "connected_seeders": 2,
            "download_speed": 1_300_000,
        },
        yellow_margin_percent=5,
        green_margin_percent=20,
    )

    assert yellow.state == "yellow"
    assert green.state == "green"
    assert yellow.attributes["yellow_margin_percent"] == 5
    assert yellow.attributes["green_margin_percent"] == 20


def test_completely_loaded_file_is_green_without_download_speed():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "loaded_size": 10_000_000,
            "torrent_size": 10_000_000,
        }
    )

    assert health.state == "green"
    assert health.reason == "fully_loaded"


def test_stream_health_estimates_large_4k_movie_conservatively():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "title": "Star Trek 4K HEVC HDR (2160p)",
            "torrent_size": 51 * 1024**3,
            "connected_seeders": 1,
            "active_peers": 1,
            "download_speed": 850_000,
            "preloaded_bytes": 160_000_000,
        }
    )

    assert health.state == "red"
    assert health.attributes["bit_rate_mbps"] == 40.0
    assert health.attributes["bit_rate_source"] == "auto_4k_large"
    assert health.attributes["speed_ratio"] == 0.17


def test_stream_health_prefers_size_and_duration_over_title_profile():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "title": "Compact 4K (2160p)",
            "torrent_size": 9_000_000_000,
            "duration_seconds": 7_200,
            "connected_seeders": 3,
            "active_peers": 4,
            "download_speed": 1_600_000,
        }
    )

    assert health.attributes["bit_rate_source"] == "size_and_duration"
    assert health.attributes["bit_rate_mbps"] == 10.0


def test_torrserver_bit_rate_wins_over_automatic_4k_profile():
    health = evaluate_stream_health(
        {
            "stat": 3,
            "title": "Large 4K (2160p)",
            "torrent_size": 60 * 1024**3,
            "bit_rate": 18_000_000,
            "connected_seeders": 3,
            "active_peers": 4,
            "download_speed": 2_500_000,
        }
    )

    assert health.attributes["bit_rate_source"] == "torrserver"
    assert health.attributes["bit_rate_mbps"] == 18.0


def test_multiple_streams_report_the_worst_state_and_counts():
    health = evaluate_streams_health(
        (
            {
                "stat": 3,
                "connected_seeders": 4,
                "active_peers": 5,
                "download_speed": 2_000_000,
            },
            {"stat": 3},
            {
                "stat": 3,
                "connected_seeders": 1,
                "active_peers": 1,
                "download_speed": 1_200_000,
                "preloaded_bytes": 64_000_000,
            },
        )
    )

    assert health.state == "red"
    assert health.attributes == {
        "estimated": True,
        "reason": "no_sources",
        "stream_count": 3,
        "green_streams": 1,
        "yellow_streams": 1,
        "red_streams": 1,
        "unknown_streams": 0,
        "worst_score": 0,
        "worst_reason": "no_sources",
    }


def test_multiple_green_streams_remain_green():
    health = evaluate_streams_health(
        (
            {
                "stat": 3,
                "connected_seeders": 4,
                "active_peers": 5,
                "download_speed": 2_000_000,
            },
            {
                "stat": 3,
                "connected_seeders": 6,
                "active_peers": 7,
                "download_speed": 3_000_000,
            },
        )
    )

    assert health.state == "green"
    assert health.attributes["green_streams"] == 2
    assert health.attributes["stream_count"] == 2


def test_starting_stream_does_not_hide_a_yellow_stream():
    health = evaluate_streams_health(
        (
            {"stat": 1},
            {
                "stat": 3,
                "connected_seeders": 1,
                "active_peers": 1,
                "download_speed": 1_200_000,
                "preloaded_bytes": 64_000_000,
            },
        )
    )

    assert health.state == "yellow"
    assert health.attributes["unknown_streams"] == 1
    assert health.attributes["yellow_streams"] == 1


def test_no_active_streams_returns_idle_with_zero_counts():
    health = evaluate_streams_health(())

    assert health.state == "idle"
    assert health.attributes["stream_count"] == 0
    assert health.attributes["red_streams"] == 0


def test_stream_health_icons_are_state_aware():
    assert stream_health_icon("red") == "mdi:alert-circle"
    assert stream_health_icon("yellow") == "mdi:alert"
    assert stream_health_icon("green") == "mdi:check-circle"
    assert stream_health_icon("unexpected") == "mdi:traffic-light"
