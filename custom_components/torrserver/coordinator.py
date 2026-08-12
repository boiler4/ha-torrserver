"""Data coordinator for TorrServer."""

from __future__ import annotations

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
