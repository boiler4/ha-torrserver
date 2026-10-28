"""Regression tests for the authoritative reader-v2 stream-health model."""

from __future__ import annotations

import unittest

from custom_components.torrserver.api import (
    _cache_readers,
    _reader_remaining_file_cached,
)
from custom_components.torrserver.stream_shadow import ReaderV2StreamTracker


def _stream(
    *,
    stat: int = 2,
    reader: int = 100,
    download_speed: float = 6_100_000,
    buffer_seconds: float = 95.7,
) -> dict:
    bit_rate = 74_300_000.0
    required_bytes = bit_rate / 8
    return {
        "hash": "private-test-key",
        "stat": stat,
        "download_speed": download_speed,
        "bit_rate": bit_rate,
        "bit_rate_source": "ffprobe_experimental",
        "bit_rate_estimated": False,
        "buffer_ahead_bytes": required_bytes * buffer_seconds,
        "buffer_measurement_source": "contiguous_completed_pieces",
        "cache_stats_available": True,
        "cache_full": False,
        "shadow_reader_positions": (reader,),
        "shadow_piece_length": 4_000_000,
        "shadow_remaining_file_cached": False,
        "shadow_current_piece_complete": True,
    }


def _apply(
    tracker: ReaderV2StreamTracker,
    torrent: dict,
    now: float,
    *,
    confirmation: float = 0,
) -> None:
    tracker.apply(
        (torrent,),
        now=now,
        window_seconds=120,
        sustainable_margin_percent=15,
        low_buffer_seconds=15,
        risk_horizon_seconds=300,
        confirmation_seconds=confirmation,
        scan_interval_seconds=10,
    )


class ShadowModelTests(unittest.TestCase):
    def test_preloading_deficit_is_not_called_sustainable_or_at_risk(self) -> None:
        tracker = ReaderV2StreamTracker()
        torrent = _stream()
        for now in (1_000.0, 1_010.0, 1_020.0, 1_030.0):
            _apply(tracker, torrent, now)

        self.assertEqual(torrent["shadow_phase"], "preloading")
        self.assertEqual(
            torrent["shadow_candidate_condition"], "preloading_unsustainable"
        )
        self.assertEqual(torrent["shadow_forecast_state"], "depleting")
        self.assertEqual(torrent["shadow_health_state"], "insufficient")
        self.assertFalse(torrent["shadow_interruption_risk"])
        self.assertEqual(torrent["shadow_eta_source"], "projected_if_playback_started")
        self.assertAlmostEqual(torrent["shadow_eta_seconds"], 280, delta=8)

    def test_playing_buffer_trend_takes_precedence_and_raises_risk(self) -> None:
        tracker = ReaderV2StreamTracker()
        bit_rate_bytes = 74_300_000 / 8
        deficit_bytes = bit_rate_bytes - 6_100_000
        torrent = _stream(stat=3)
        for index, now in enumerate((1_000.0, 1_010.0, 1_020.0, 1_030.0)):
            torrent["shadow_reader_positions"] = (100 + index * 10,)
            torrent["buffer_ahead_bytes"] = bit_rate_bytes * 95.7 - deficit_bytes * (
                index * 10
            )
            _apply(tracker, torrent, now)

        self.assertEqual(torrent["shadow_phase"], "playing")
        self.assertEqual(torrent["shadow_candidate_condition"], "at_risk")
        self.assertEqual(torrent["shadow_eta_source"], "measured_buffer_trend")
        self.assertTrue(torrent["shadow_interruption_risk"])
        self.assertEqual(torrent["shadow_health_state"], "insufficient")

    def test_complete_remaining_file_is_protected_even_at_zero_speed(self) -> None:
        tracker = ReaderV2StreamTracker()
        torrent = _stream(stat=3, download_speed=0)
        torrent["shadow_remaining_file_cached"] = True
        _apply(tracker, torrent, 1_000.0)

        self.assertEqual(torrent["shadow_condition"], "protected")
        self.assertEqual(torrent["shadow_health_state"], "protected")
        self.assertEqual(torrent["shadow_forecast_state"], "sustainable")
        self.assertIsNone(torrent["shadow_eta_seconds"])
        self.assertFalse(torrent["shadow_interruption_risk"])

    def test_confirmed_risk_requires_sustained_recovery_to_clear(self) -> None:
        tracker = ReaderV2StreamTracker()
        torrent = _stream(stat=3, buffer_seconds=4)
        torrent["shadow_current_piece_complete"] = False
        for index, now in enumerate((1_000.0, 1_010.0, 1_020.0)):
            torrent["shadow_reader_positions"] = (100 + index,)
            _apply(tracker, torrent, now, confirmation=0)
        self.assertTrue(torrent["shadow_interruption_risk"])

        torrent["shadow_remaining_file_cached"] = True
        _apply(tracker, torrent, 1_030.0, confirmation=0)
        self.assertTrue(torrent["shadow_interruption_risk"])
        self.assertEqual(torrent["shadow_risk_transition_pending_seconds"], 30)

        _apply(tracker, torrent, 1_060.0, confirmation=0)
        self.assertFalse(torrent["shadow_interruption_risk"])

    def test_startup_low_buffer_waits_for_fresh_samples(self) -> None:
        tracker = ReaderV2StreamTracker()
        torrent = _stream(stat=3, buffer_seconds=4)
        torrent["shadow_current_piece_complete"] = False

        for index, now in enumerate((1_000.0, 1_010.0)):
            torrent["shadow_reader_positions"] = (100 + index,)
            _apply(tracker, torrent, now)
            self.assertEqual(torrent["shadow_candidate_condition"], "measuring")
            self.assertFalse(torrent["shadow_interruption_risk"])

        torrent["shadow_reader_positions"] = (102,)
        _apply(tracker, torrent, 1_020.0)
        self.assertTrue(torrent["shadow_interruption_risk"])
        self.assertEqual(torrent["shadow_candidate_condition"], "at_risk")

    def test_seek_immediately_clears_active_risk_and_eta(self) -> None:
        tracker = ReaderV2StreamTracker()
        torrent = _stream(stat=3, buffer_seconds=4)
        torrent["shadow_current_piece_complete"] = False
        for index, now in enumerate((1_000.0, 1_010.0, 1_020.0)):
            torrent["shadow_reader_positions"] = (100 + index,)
            _apply(tracker, torrent, now)
        self.assertTrue(torrent["shadow_interruption_risk"])

        torrent["shadow_reader_positions"] = (500,)
        _apply(tracker, torrent, 1_030.0)
        self.assertEqual(torrent["shadow_phase"], "seek")
        self.assertEqual(torrent["shadow_condition"], "measuring")
        self.assertEqual(torrent["shadow_candidate_condition"], "measuring")
        self.assertEqual(torrent["shadow_forecast_state"], "measuring")
        self.assertFalse(torrent["shadow_interruption_risk"])
        self.assertIsNone(torrent["shadow_eta_seconds"])

        torrent["shadow_reader_positions"] = (501,)
        _apply(tracker, torrent, 1_040.0)
        self.assertEqual(torrent["shadow_candidate_condition"], "measuring")
        self.assertFalse(torrent["shadow_interruption_risk"])

    def test_pause_clears_risk_without_recovery_hysteresis_and_resume_remeasures(
        self,
    ) -> None:
        tracker = ReaderV2StreamTracker()
        torrent = _stream(stat=3)
        for index, now in enumerate((1_000.0, 1_010.0, 1_020.0, 1_030.0)):
            torrent["shadow_reader_positions"] = (100 + index,)
            _apply(tracker, torrent, now)
        self.assertTrue(torrent["shadow_interruption_risk"])

        torrent["shadow_reader_positions"] = (103,)
        _apply(tracker, torrent, 1_070.0)
        self.assertEqual(torrent["shadow_phase"], "paused")
        self.assertEqual(torrent["shadow_condition"], "paused")
        self.assertEqual(torrent["shadow_candidate_condition"], "paused")
        self.assertEqual(torrent["shadow_forecast_state"], "sustainable")
        self.assertFalse(torrent["shadow_interruption_risk"])
        self.assertIsNone(torrent["shadow_eta_seconds"])
        self.assertIsNone(torrent["shadow_risk_transition_pending_seconds"])

        torrent["shadow_reader_positions"] = (104,)
        _apply(tracker, torrent, 1_080.0)
        self.assertEqual(torrent["shadow_phase"], "playing")
        self.assertEqual(torrent["shadow_condition"], "measuring")
        self.assertEqual(torrent["shadow_candidate_condition"], "measuring")
        self.assertEqual(torrent["shadow_forecast_state"], "measuring")
        self.assertFalse(torrent["shadow_interruption_risk"])
        self.assertIsNone(torrent["shadow_eta_seconds"])

    def test_pause_seek_and_drop_do_not_leave_stale_risk(self) -> None:
        tracker = ReaderV2StreamTracker()
        torrent = _stream(stat=3)
        for index, now in enumerate((1_000.0, 1_010.0)):
            torrent["shadow_reader_positions"] = (100 + index,)
            _apply(tracker, torrent, now)

        torrent["shadow_reader_positions"] = (101,)
        _apply(tracker, torrent, 1_050.0)
        self.assertEqual(torrent["shadow_phase"], "paused")
        self.assertFalse(torrent["shadow_interruption_risk"])

        torrent["shadow_reader_positions"] = (500,)
        _apply(tracker, torrent, 1_060.0)
        self.assertEqual(torrent["shadow_phase"], "seek")
        self.assertEqual(torrent["shadow_candidate_condition"], "measuring")

        tracker.apply(
            (),
            now=1_070.0,
            window_seconds=120,
            sustainable_margin_percent=15,
            low_buffer_seconds=15,
            risk_horizon_seconds=300,
            confirmation_seconds=0,
            scan_interval_seconds=10,
        )
        fresh = _stream(stat=2)
        _apply(tracker, fresh, 1_080.0)
        self.assertEqual(fresh["shadow_phase"], "preloading")
        self.assertFalse(fresh["shadow_interruption_risk"])


class CacheEvidenceTests(unittest.TestCase):
    def test_reader_at_zero_is_valid_but_malformed_zero_is_not(self) -> None:
        cache = {
            "Readers": [
                {"Reader": 0, "Start": 0, "End": 10},
                {"Reader": "bad", "Start": 0, "End": 10},
            ]
        }
        self.assertEqual(len(_cache_readers(cache)), 1)
        self.assertEqual(_cache_readers(cache)[0]["Reader"], 0)

    def test_remaining_file_requires_every_piece_complete(self) -> None:
        torrent = {"file_stats": [{"id": 1, "length": 1_000}]}
        reader = {"Reader": 2, "Start": 0, "End": 10}
        pieces = {
            str(piece_id): {"Id": piece_id, "Completed": True}
            for piece_id in range(2, 10)
        }
        cache = {"PiecesLength": 100, "Pieces": pieces}
        self.assertTrue(_reader_remaining_file_cached(torrent, cache, reader))

        pieces["7"]["Completed"] = False
        self.assertFalse(_reader_remaining_file_cached(torrent, cache, reader))

    def test_file_boundary_ambiguity_never_proves_protection(self) -> None:
        torrent = {
            "file_stats": [
                {"id": 1, "length": 150},
                {"id": 2, "length": 150},
            ]
        }
        cache = {
            "PiecesLength": 100,
            "Pieces": {
                "1": {"Id": 1, "Completed": True},
                "2": {"Id": 2, "Completed": True},
            },
        }
        reader = {"Reader": 1, "Start": 0, "End": 3}
        self.assertIsNone(_reader_remaining_file_cached(torrent, cache, reader))


if __name__ == "__main__":
    unittest.main()
