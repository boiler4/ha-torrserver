"""Data coordinator for TorrServer."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from time import monotonic

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
from .stream_health import StreamHealthTracker
from .stream_metrics import StreamSpeedTracker
from .stream_shadow import ReaderV2StreamTracker
from .telemetry import stream_diagnostic_sample

_LOGGER = logging.getLogger(__name__)


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
        stream_shadow_enabled: bool,
        stream_shadow_window: float,
        stream_shadow_margin: float,
        stream_shadow_risk_horizon: float,
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
        self.stream_shadow_enabled = stream_shadow_enabled
        self.stream_shadow_window = stream_shadow_window
        self.stream_shadow_margin = stream_shadow_margin
        self.stream_shadow_risk_horizon = stream_shadow_risk_horizon
        self.scan_interval_seconds = scan_interval
        self._speed_tracker = StreamSpeedTracker()
        self._health_tracker = StreamHealthTracker()
        self._forecast_tracker = StreamForecastTracker()
        self._reader_v2_tracker = ReaderV2StreamTracker()
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
            sample = stream_diagnostic_sample(
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

    @staticmethod
    def _promote_reader_v2_results(data: TorrServerData) -> None:
        """Make the validated v2 assessment authoritative for existing entities."""
        for torrent in data.streaming_torrents:
            health = torrent.get("shadow_health_state")
            buffer_mode = torrent.get("shadow_buffer_mode")
            forecast = torrent.get("shadow_forecast_state")
            if health is None or buffer_mode is None or forecast is None:
                continue

            torrent["stream_health_model"] = "reader_v2"
            torrent["stabilized_stream_health_state"] = health
            torrent["stabilized_stream_health_reason"] = torrent.get(
                "shadow_reason"
            )
            torrent["stream_health_candidate_state"] = torrent.get(
                "shadow_health_state"
            )
            torrent["stream_health_candidate_reason"] = torrent.get(
                "shadow_candidate_reason"
            )
            torrent["stream_health_pending_seconds"] = torrent.get(
                "shadow_transition_pending_seconds"
            )
            torrent["buffer_mode"] = buffer_mode
            torrent["stream_forecast_state"] = forecast
            torrent["stream_forecast_reason"] = torrent.get("shadow_reason")
            torrent["stream_interruption_risk"] = bool(
                torrent.get("shadow_interruption_risk")
            )
            torrent["stream_interruption_eta_seconds"] = torrent.get(
                "shadow_eta_seconds"
            )
            torrent["stream_risk_confirmation_pending_seconds"] = torrent.get(
                "shadow_risk_transition_pending_seconds"
            )
            ratio = torrent.get("shadow_long_speed_ratio")
            torrent["stream_speed_margin_percent"] = (
                round((float(ratio) - 1) * 100, 1) if ratio is not None else None
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
            if self.stream_shadow_enabled:
                self._reader_v2_tracker.apply(
                    data.streaming_torrents,
                    now=now,
                    window_seconds=self.stream_shadow_window,
                    sustainable_margin_percent=self.stream_shadow_margin,
                    low_buffer_seconds=self.stream_low_buffer_seconds,
                    risk_horizon_seconds=self.stream_shadow_risk_horizon,
                    confirmation_seconds=self.stream_risk_confirmation,
                    scan_interval_seconds=self.scan_interval_seconds,
                )
            self._log_stream_diagnostics(data)
            if self.stream_shadow_enabled:
                self._promote_reader_v2_results(data)
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
