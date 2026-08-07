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
from .stream_metrics import StreamSpeedTracker

_LOGGER = logging.getLogger(__name__)


class TorrServerDataUpdateCoordinator(DataUpdateCoordinator[TorrServerData]):
    """Coordinate a single API poll for all TorrServer entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TorrServerApiClient,
        scan_interval: int,
        stream_yellow_margin: float,
        stream_green_margin: float,
        stream_average_window: float,
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
        self.stream_yellow_margin = stream_yellow_margin
        self.stream_green_margin = stream_green_margin
        self.stream_average_window = stream_average_window
        self._speed_tracker = StreamSpeedTracker()
        self._repair_issue_id = f"ffprobe_unavailable_{entry_id}"

    async def _async_update_data(self) -> TorrServerData:
        """Fetch the latest TorrServer status."""
        try:
            data = await self.client.async_get_data()
            self._speed_tracker.apply(
                data.streaming_torrents,
                now=monotonic(),
                window_seconds=self.stream_average_window,
                cache_full_threshold=CACHE_FULL_THRESHOLD,
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
