"""TorrServer integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TorrServerApiClient
from .const import (
    CONF_EXPERIMENTAL_FFPROBE,
    CONF_SCAN_INTERVAL,
    CONF_STREAM_AVERAGE_WINDOW,
    CONF_STREAM_DOWNGRADE_DELAY,
    CONF_STREAM_LOW_BUFFER_SECONDS,
    CONF_STREAM_PRELOAD_MARGIN,
    CONF_STREAM_PROTECTED_BUFFER_SECONDS,
    CONF_STREAM_STABLE_MARGIN,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_EXPERIMENTAL_FFPROBE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STREAM_AVERAGE_WINDOW,
    DEFAULT_STREAM_DOWNGRADE_DELAY,
    DEFAULT_STREAM_LOW_BUFFER_SECONDS,
    DEFAULT_STREAM_PRELOAD_MARGIN,
    DEFAULT_STREAM_PROTECTED_BUFFER_SECONDS,
    DEFAULT_STREAM_STABLE_MARGIN,
    DEFAULT_VERIFY_SSL,
)
from .coordinator import TorrServerDataUpdateCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

TorrServerConfigEntry = ConfigEntry[TorrServerDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TorrServerConfigEntry) -> bool:
    """Set up TorrServer from a config entry."""
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    average_window = float(
        entry.options.get(
            CONF_STREAM_AVERAGE_WINDOW,
            max(DEFAULT_STREAM_AVERAGE_WINDOW, scan_interval),
        )
    )
    client = TorrServerApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        experimental_ffprobe=bool(
            entry.options.get(CONF_EXPERIMENTAL_FFPROBE, DEFAULT_EXPERIMENTAL_FFPROBE)
        ),
    )
    coordinator = TorrServerDataUpdateCoordinator(
        hass,
        client,
        scan_interval,
        float(
            entry.options.get(CONF_STREAM_STABLE_MARGIN, DEFAULT_STREAM_STABLE_MARGIN)
        ),
        float(
            entry.options.get(CONF_STREAM_PRELOAD_MARGIN, DEFAULT_STREAM_PRELOAD_MARGIN)
        ),
        average_window,
        float(
            entry.options.get(
                CONF_STREAM_LOW_BUFFER_SECONDS, DEFAULT_STREAM_LOW_BUFFER_SECONDS
            )
        ),
        float(
            entry.options.get(
                CONF_STREAM_PROTECTED_BUFFER_SECONDS,
                DEFAULT_STREAM_PROTECTED_BUFFER_SECONDS,
            )
        ),
        float(
            entry.options.get(
                CONF_STREAM_DOWNGRADE_DELAY, DEFAULT_STREAM_DOWNGRADE_DELAY
            )
        ),
        entry.entry_id,
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
