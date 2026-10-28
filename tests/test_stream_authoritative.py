"""Regression tests for promoting reader-v2 results to existing HA entities."""

from __future__ import annotations

import unittest

from custom_components.torrserver.api import TorrServerData
from custom_components.torrserver.coordinator import TorrServerDataUpdateCoordinator
from custom_components.torrserver.stream_forecast import evaluate_stream_forecast
from custom_components.torrserver.stream_health import evaluate_stream_health


class AuthoritativeStreamModelTests(unittest.TestCase):
    def test_reader_v2_drives_existing_health_forecast_and_risk_fields(self) -> None:
        torrent = {
            "stat": 3,
            "bit_rate": 74_300_000,
            "download_speed": 6_100_000,
            "buffer_ahead_bytes": 889_000_000,
            "buffer_measurement_source": "contiguous_completed_pieces",
            "cache_stats_available": True,
            "streaming_reader_count": 1,
            "shadow_health_state": "insufficient",
            "shadow_buffer_mode": "draining",
            "shadow_forecast_state": "depleting",
            "shadow_condition": "temporarily_protected",
            "shadow_candidate_condition": "at_risk",
            "shadow_reason": "buffer_masks_throughput_deficit",
            "shadow_candidate_reason": "projected_interruption_within_horizon",
            "shadow_phase": "playing",
            "shadow_confidence": "high",
            "shadow_interruption_risk": False,
            "shadow_candidate_risk": True,
            "shadow_eta_seconds": 278.8,
            "shadow_eta_source": "measured_buffer_trend",
            "shadow_long_speed_ratio": 0.657,
            "shadow_short_speed_ratio": 0.61,
            "shadow_transition_pending_seconds": 10.0,
            "shadow_risk_transition_pending_seconds": 5.0,
        }
        data = TorrServerData(torrents=(torrent,))

        TorrServerDataUpdateCoordinator._promote_reader_v2_results(data)

        self.assertEqual(torrent["stream_health_model"], "reader_v2")
        self.assertEqual(torrent["stabilized_stream_health_state"], "insufficient")
        self.assertEqual(torrent["buffer_mode"], "draining")
        self.assertEqual(torrent["stream_forecast_state"], "depleting")
        self.assertFalse(torrent["stream_interruption_risk"])
        self.assertEqual(torrent["stream_interruption_eta_seconds"], 278.8)
        self.assertEqual(torrent["stream_speed_margin_percent"], -34.3)

        health = evaluate_stream_health(torrent)
        self.assertEqual(health.state, "insufficient")
        self.assertEqual(health.attributes["model"], "reader_v2")
        self.assertEqual(health.attributes["phase"], "playing")
        self.assertEqual(health.attributes["buffer_mode"], "draining")

        forecast = evaluate_stream_forecast(torrent)
        self.assertEqual(forecast.state, "depleting")
        self.assertFalse(forecast.risk)
        self.assertEqual(forecast.eta_seconds, 278.8)
        self.assertEqual(forecast.attributes["model"], "reader_v2")


if __name__ == "__main__":
    unittest.main()
