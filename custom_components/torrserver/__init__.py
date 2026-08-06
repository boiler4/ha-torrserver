"""TorrServer integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TorrServerApiClient
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
)
from .coordinator import TorrServerDataUpdateCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

TorrServerConfigEntry = ConfigEntry[TorrServerDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TorrServerConfigEntry) -> bool:
    """Set up TorrServer from a config entry."""
    client = TorrServerApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )
    coordinator = TorrServerDataUpdateCoordinator(
        hass,
        client,
        int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TorrServerConfigEntry) -> bool:
    """Unload a TorrServer config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: TorrServerConfigEntry
) -> None:
    """Reload TorrServer after options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)
