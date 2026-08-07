"""Data coordinator for TorrServer."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TorrServerApiClient,
    TorrServerAuthenticationError,
    TorrServerCannotConnect,
    TorrServerData,
)
from .const import DOMAIN

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

    async def _async_update_data(self) -> TorrServerData:
        """Fetch the latest TorrServer status."""
        try:
            return await self.client.async_get_data()
        except TorrServerAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except TorrServerCannotConnect as err:
            raise UpdateFailed(f"Error communicating with TorrServer: {err}") from err
