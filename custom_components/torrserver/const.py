"""Constants for the TorrServer integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "torrserver"
PLATFORMS: Final = ["binary_sensor", "sensor"]

CONF_URL: Final = "url"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DOWNLOAD_THRESHOLD: Final = "download_threshold"
CONF_EXPERIMENTAL_FFPROBE: Final = "experimental_ffprobe"

DEFAULT_URL: Final = "http://127.0.0.1:8090"
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_SCAN_INTERVAL: Final = 10
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 300
DEFAULT_DOWNLOAD_THRESHOLD: Final = 1.0
DEFAULT_EXPERIMENTAL_FFPROBE: Final = False

TORRENT_ADDED: Final = 0
TORRENT_GETTING_INFO: Final = 1
TORRENT_PRELOAD: Final = 2
TORRENT_WORKING: Final = 3
TORRENT_CLOSED: Final = 4
TORRENT_IN_DB: Final = 5

ACTIVE_STATES: Final = frozenset(
    {
        TORRENT_ADDED,
        TORRENT_GETTING_INFO,
        TORRENT_PRELOAD,
        TORRENT_WORKING,
    }
)
