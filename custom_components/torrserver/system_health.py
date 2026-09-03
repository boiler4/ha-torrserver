"""System health information for TorrServer."""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register TorrServer system health information."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return a privacy-conscious summary for configured instances."""
    entries = hass.config_entries.async_entries(DOMAIN)
    coordinators = [
        entry.runtime_data
        for entry in entries
        if entry.state is ConfigEntryState.LOADED
    ]
    connected = [item for item in coordinators if item.last_update_success]
    return {
        "configured_instances": len(entries),
        "connected_instances": len(connected),
        "server_versions": ", ".join(
            sorted(
                {
                    item.data.version
                    for item in connected
                    if item.data and item.data.version
                }
            )
        )
        or "unknown",
        "ffprobe_status": ", ".join(
            sorted({item.data.ffprobe_status for item in connected if item.data})
        )
        or "unknown",
        "ffprobe_failures": max(
            (item.data.ffprobe_failures for item in connected if item.data),
            default=0,
        ),
        "ffprobe_last_errors": ", ".join(
            sorted(
                {
                    item.data.ffprobe_last_error
                    for item in connected
                    if item.data and item.data.ffprobe_last_error
                }
            )
        )
        or "none",
    }
