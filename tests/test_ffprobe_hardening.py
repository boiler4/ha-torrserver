"""Focused regression tests for ffprobe resilience and bitrate reporting."""

from __future__ import annotations

import unittest
from collections import OrderedDict

from custom_components.torrserver import api
from custom_components.torrserver.api import (
    TorrServerApiClient,
    TorrServerCannotConnect,
)
from custom_components.torrserver.stream_health import evaluate_stream_health


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _torrent(hash_value: str = "test-hash") -> dict:
    return {
        "hash": hash_value,
        "stat": 3,
        "download_speed": 4_000_000,
        "preloaded_bytes": api._FFPROBE_MIN_PRELOADED_BYTES,
        "torrent_size": 10_000,
        "file_stats": [
            {"id": 1, "length": 500},
            {"id": 2, "length": 1_000},
        ],
    }


def _cache_state() -> dict:
    return {
        "PiecesLength": 100,
        "Readers": [{"Reader": 6, "Start": 5, "End": 10}],
    }


class ProbeRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.original_monotonic = api.monotonic
        api.monotonic = self.clock
        self.client = TorrServerApiClient(
            object(), "http://torrserver.invalid", experimental_ffprobe=True
        )

    def tearDown(self) -> None:
        api.monotonic = self.original_monotonic

    async def test_failure_backoff_retry_success_and_cache(self) -> None:
        calls = 0

        async def fail_probe(_torrent_hash: str, _file_id: int) -> dict:
            nonlocal calls
            calls += 1
            raise TorrServerCannotConnect("TorrServer returned HTTP 400")

        self.client.async_get_media_probe = fail_probe
        first = _torrent()
        await self.client._async_apply_experimental_probe(
            (first,), {"test-hash": _cache_state()}
        )
        self.assertEqual(calls, 1)
        self.assertEqual(self.client._ffprobe_status, "retrying")
        self.assertEqual(first["ffprobe_last_error"], "http_400")
        self.assertEqual(first["ffprobe_failure_count"], 1)
        self.assertEqual(first["active_file_size"], 1_000)

        async def successful_probe(_torrent_hash: str, _file_id: int) -> dict:
            nonlocal calls
            calls += 1
            return {"format": {"bit_rate": "20045351", "duration": "6393.387"}}

        self.client.async_get_media_probe = successful_probe
        during_backoff = _torrent()
        await self.client._async_apply_experimental_probe(
            (during_backoff,), {"test-hash": _cache_state()}
        )
        self.assertEqual(calls, 1)
        self.assertEqual(during_backoff["ffprobe_status"], "retrying")

        self.clock.advance(15)
        retried = _torrent()
        await self.client._async_apply_experimental_probe(
            (retried,), {"test-hash": _cache_state()}
        )
        self.assertEqual(calls, 2)
        self.assertEqual(self.client._ffprobe_status, "available")
        self.assertEqual(retried["bit_rate"], 20_045_351)
        self.assertEqual(retried["bit_rate_source"], "ffprobe_experimental")
        self.assertFalse(retried["bit_rate_estimated"])

        cached = _torrent()
        await self.client._async_apply_experimental_probe(
            (cached,), {"test-hash": _cache_state()}
        )
        self.assertEqual(calls, 2)
        self.assertEqual(cached["ffprobe_status"], "cached")
        self.assertEqual(cached["bit_rate"], 20_045_351)

    async def test_warning_only_after_three_failures(self) -> None:
        async def fail_probe(_torrent_hash: str, _file_id: int) -> dict:
            raise TorrServerCannotConnect("Request timed out")

        self.client.async_get_media_probe = fail_probe
        for expected_failures, delay, expected_status in (
            (1, 15, "retrying"),
            (2, 30, "retrying"),
            (3, 60, "unavailable"),
        ):
            current = _torrent()
            await self.client._async_apply_experimental_probe(
                (current,), {"test-hash": _cache_state()}
            )
            self.assertEqual(self.client._ffprobe_failures, expected_failures)
            self.assertEqual(self.client._ffprobe_status, expected_status)
            self.assertEqual(self.client._ffprobe_last_error, "timeout")
            self.assertEqual(self.client._ffprobe_retry_seconds, delay)
            self.clock.advance(delay)

        await self.client._async_apply_experimental_probe((), {})
        self.assertEqual(self.client._ffprobe_status, "waiting_for_stream")
        self.assertEqual(self.client._ffprobe_failures, 0)

    def test_probe_cache_is_bounded_and_expires(self) -> None:
        self.client._probe_cache = OrderedDict(
            (
                (f"hash-{index}", 1),
                api._ProbeCacheEntry(1.0, 1.0, self.clock.now),
            )
            for index in range(api._FFPROBE_CACHE_MAX_ENTRIES + 1)
        )
        self.client._prune_probe_state(self.clock.now)
        self.assertEqual(len(self.client._probe_cache), api._FFPROBE_CACHE_MAX_ENTRIES)
        self.clock.advance(api._FFPROBE_CACHE_TTL)
        self.client._prune_probe_state(self.clock.now)
        self.assertFalse(self.client._probe_cache)


class BitRateTests(unittest.TestCase):
    def test_active_file_size_wins_over_multi_file_torrent_size(self) -> None:
        health = evaluate_stream_health(
            {
                "stat": 3,
                "download_speed": 2_000_000,
                "torrent_size": 10_000_000_000,
                "active_file_size": 1_000_000_000,
                "duration_seconds": 1_000,
            }
        )
        self.assertEqual(health.attributes["bit_rate_mbps"], 8.0)
        self.assertEqual(
            health.attributes["bit_rate_source"], "active_file_size_and_duration"
        )
        self.assertTrue(health.attributes["bit_rate_estimated"])


class BitRateSourceTests(unittest.TestCase):
    def test_measured_bitrate_is_not_marked_estimated(self) -> None:
        torrent = {
            "hash": "test-hash",
            "stat": 3,
            "download_speed": 4_000_000,
            "bit_rate": 20_045_351,
            "bit_rate_source": "ffprobe_experimental",
            "bit_rate_estimated": False,
            "ffprobe_status": "success",
        }
        health = evaluate_stream_health(torrent)
        self.assertEqual(health.attributes["bit_rate_mbps"], 20.05)
        self.assertFalse(health.attributes["bit_rate_estimated"])

    def test_title_heuristic_is_explicitly_estimated(self) -> None:
        health = evaluate_stream_health(
            {"stat": 3, "title": "Example 2160p", "download_speed": 4_000_000}
        )
        self.assertEqual(health.attributes["bit_rate_mbps"], 16.0)
        self.assertEqual(health.attributes["bit_rate_source"], "auto_4k_compact")
        self.assertTrue(health.attributes["bit_rate_estimated"])


if __name__ == "__main__":
    unittest.main()
