"""Diagnostics support for TorrServer."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import TorrServerConfigEntry

_REDACT_CONFIG = {"password", "username"}
_REDACT_TORRENT = {
    "data",
    "file_stats",
    "hash",
    "name",
    "path",
    "poster",
    "title",
    "torrs_hash",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TorrServerConfigEntry
) -> dict[str, Any]:
    """Return privacy-conscious diagnostics for a config entry."""
    data = entry.runtime_data.data
    active = [
        async_redact_data(dict(item), _REDACT_TORRENT) for item in data.active_torrents
    ]
    return {
        "entry": async_redact_data(dict(entry.data), _REDACT_CONFIG),
        "options": dict(entry.options),
        "server_version": data.version,
        "last_update_success": entry.runtime_data.last_update_success,
        "torrent_count": len(data.torrents),
        "active_torrent_count": len(data.active_torrents),
        "active_torrents": active,
    }
