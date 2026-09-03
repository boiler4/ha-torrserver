"""Data coordinator for TorrServer."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TorrServerApiClient,
    TorrServerAuthenticationError,
    TorrServerCannotConnect,
    TorrServerData,
)
from .const import CACHE_FULL_THRESHOLD, DOMAIN
from .stream_forecast import StreamForecastTracker
from .stream_health import StreamHealthTracker, evaluate_stream_health
from .stream_metrics import StreamSpeedTracker

_LOGGER = logging.getLogger(__name__)


def _stream_diagnostic_sample(
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


class TorrServerDataUpdateCoordinator(DataUpdateCoordinator[TorrServerData]):
    """Coordinate a single API poll for all TorrServer entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TorrServerApiClient,
        scan_interval: int,
        stream_stable_margin: float,
        stream_preload_margin: float,
        stream_average_window: float,
        stream_low_buffer_seconds: float,
        stream_protected_buffer_seconds: float,
        stream_downgrade_delay: float,
        stream_risk_horizon: float,
        stream_risk_confirmation: float,
        entry_id: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.stream_stable_margin = stream_stable_margin
        self.stream_preload_margin = stream_preload_margin
        self.stream_average_window = stream_average_window
        self.stream_low_buffer_seconds = stream_low_buffer_seconds
        self.stream_protected_buffer_seconds = stream_protected_buffer_seconds
        self.stream_downgrade_delay = stream_downgrade_delay
        self.stream_risk_horizon = stream_risk_horizon
        self.stream_risk_confirmation = stream_risk_confirmation
        self._speed_tracker = StreamSpeedTracker()
        self._health_tracker = StreamHealthTracker()
        self._forecast_tracker = StreamForecastTracker()
        self._repair_issue_id = f"ffprobe_unavailable_{entry_id}"
        self._diagnostic_sequence = 0
        self._had_streams = False

    def _log_stream_diagnostics(self, data: TorrServerData) -> None:
        """Emit detailed samples without torrent identifiers or media metadata."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        streams = data.streaming_torrents
        if not streams:
            if self._had_streams:
                _LOGGER.debug(
                    "stream_health_sample %s",
                    json.dumps(
                        {
                            "event": "stream_health_idle",
                            "last_sequence": self._diagnostic_sequence,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                )
            self._had_streams = False
            return

        self._had_streams = True
        self._diagnostic_sequence += 1
        for index, torrent in enumerate(streams, start=1):
            sample = _stream_diagnostic_sample(
                torrent,
                sequence=self._diagnostic_sequence,
                index=index,
                total=len(streams),
                stable_margin_percent=self.stream_stable_margin,
                preload_margin_percent=self.stream_preload_margin,
                low_buffer_seconds=self.stream_low_buffer_seconds,
                protected_buffer_seconds=self.stream_protected_buffer_seconds,
                ffprobe_status=data.ffprobe_status,
                ffprobe_failures=data.ffprobe_failures,
                ffprobe_last_error=data.ffprobe_last_error,
                ffprobe_retry_seconds=data.ffprobe_retry_seconds,
            )
            _LOGGER.debug(
                "stream_health_sample %s",
                json.dumps(sample, separators=(",", ":"), sort_keys=True),
            )

    async def _async_update_data(self) -> TorrServerData:
        """Fetch the latest TorrServer status."""
        try:
            data = await self.client.async_get_data()
            now = monotonic()
            self._speed_tracker.apply(
                data.streaming_torrents,
                now=now,
                window_seconds=self.stream_average_window,
                cache_full_threshold=CACHE_FULL_THRESHOLD,
            )
            self._health_tracker.apply(
                data.streaming_torrents,
                now=now,
                stable_margin_percent=self.stream_stable_margin,
                preload_margin_percent=self.stream_preload_margin,
                low_buffer_seconds=self.stream_low_buffer_seconds,
                protected_buffer_seconds=self.stream_protected_buffer_seconds,
                downgrade_delay_seconds=self.stream_downgrade_delay,
            )
            self._forecast_tracker.apply(
                data.streaming_torrents,
                now=now,
                risk_horizon_seconds=self.stream_risk_horizon,
                confirmation_seconds=self.stream_risk_confirmation,
                stable_margin_percent=self.stream_stable_margin,
                preload_margin_percent=self.stream_preload_margin,
                low_buffer_seconds=self.stream_low_buffer_seconds,
                protected_buffer_seconds=self.stream_protected_buffer_seconds,
            )
            self._log_stream_diagnostics(data)
            if data.ffprobe_status == "unavailable":
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    self._repair_issue_id,
                    is_fixable=False,
                    is_persistent=False,
                    learn_more_url=(
                        "https://github.com/boiler4/ha-torrserver"
                        "#experimental-real-bitrate-ffprobe"
                    ),
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="ffprobe_unavailable",
                    translation_placeholders={"url": self.client.base_url},
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)
            return data
        except TorrServerAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except TorrServerCannotConnect as err:
            raise UpdateFailed(f"Error communicating with TorrServer: {err}") from err
