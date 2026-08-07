"""Tests for cache-aware rolling stream speed."""

from custom_components.torrserver.stream_metrics import StreamSpeedTracker


def _torrent(speed: int, preloaded: int = 50, preload_size: int = 100):
    return {
        "hash": "abc",
        "download_speed": speed,
        "preloaded_bytes": preloaded,
        "preload_size": preload_size,
    }


def test_tracker_builds_a_per_stream_rolling_average():
    tracker = StreamSpeedTracker()
    first = _torrent(1_000_000)
    second = _torrent(2_000_000)

    tracker.apply((first,), now=0, window_seconds=15, cache_full_threshold=95)
    tracker.apply((second,), now=5, window_seconds=15, cache_full_threshold=95)

    assert first["average_speed_source"] == "measuring"
    assert second["average_download_speed"] == 1_500_000
    assert second["average_speed_source"] == "rolling_average"
    assert second["speed_sample_count"] == 2


def test_zero_speed_is_held_when_target_cache_is_full():
    tracker = StreamSpeedTracker()
    tracker.apply(
        (_torrent(1_000_000),), now=0, window_seconds=15, cache_full_threshold=95
    )
    tracker.apply(
        (_torrent(2_000_000),), now=5, window_seconds=15, cache_full_threshold=95
    )
    paused = _torrent(0, preloaded=96)

    tracker.apply((paused,), now=10, window_seconds=15, cache_full_threshold=95)

    assert paused["cache_full"] is True
    assert paused["average_download_speed"] == 1_500_000
    assert paused["average_speed_source"] == "held_while_cache_full"
    assert paused["speed_sample_count"] == 2


def test_zero_speed_is_counted_after_cache_drains():
    tracker = StreamSpeedTracker()
    tracker.apply(
        (_torrent(2_000_000),), now=0, window_seconds=15, cache_full_threshold=95
    )
    tracker.apply(
        (_torrent(2_000_000),), now=5, window_seconds=15, cache_full_threshold=95
    )
    drained = _torrent(0, preloaded=50)

    tracker.apply((drained,), now=10, window_seconds=15, cache_full_threshold=95)

    assert drained["cache_full"] is False
    assert drained["average_download_speed"] == 4_000_000 / 3
    assert drained["average_speed_source"] == "rolling_average"


def test_full_cache_without_history_does_not_claim_a_failed_download():
    tracker = StreamSpeedTracker()
    paused = _torrent(0, preloaded=100)

    tracker.apply((paused,), now=0, window_seconds=15, cache_full_threshold=95)

    assert paused["average_download_speed"] is None
    assert paused["average_speed_source"] == "cache_full_no_history"


def test_tracker_uses_official_cache_fill_and_reader_buffer_trend():
    tracker = StreamSpeedTracker()
    first = {
        "hash": "abc",
        "download_speed": 2_000_000,
        "cache_fill_percent": 100,
        "buffer_ahead_bytes": 100_000_000,
    }
    second = {
        "hash": "abc",
        "download_speed": 0,
        "cache_fill_percent": 100,
        "buffer_ahead_bytes": 120_000_000,
    }

    tracker.apply((first,), now=0, window_seconds=15, cache_full_threshold=95)
    tracker.apply((second,), now=5, window_seconds=15, cache_full_threshold=95)

    assert second["cache_full"] is True
    assert second["average_download_speed"] == 2_000_000
    assert second["average_speed_source"] == "held_while_cache_full"
    assert second["buffer_trend_bytes_per_second"] == 4_000_000
    assert second["buffer_sample_count"] == 2
