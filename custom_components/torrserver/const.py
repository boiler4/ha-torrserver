"""Constants for the TorrServer integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "torrserver"
PLATFORMS: Final = ["binary_sensor", "sensor"]

CONF_URL: Final = "url"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DOWNLOAD_THRESHOLD: Final = "download_threshold"
CONF_DOWNLOAD_THRESHOLD_MBPS: Final = "download_threshold_mbps"
CONF_EXPERIMENTAL_FFPROBE: Final = "experimental_ffprobe"
CONF_STREAM_AVERAGE_WINDOW: Final = "stream_average_window"
CONF_STREAM_STABLE_MARGIN: Final = "stream_stable_margin"
CONF_STREAM_PRELOAD_MARGIN: Final = "stream_preload_margin"
CONF_STREAM_LOW_BUFFER_SECONDS: Final = "stream_low_buffer_seconds"
CONF_STREAM_PROTECTED_BUFFER_SECONDS: Final = "stream_protected_buffer_seconds"
CONF_STREAM_DOWNGRADE_DELAY: Final = "stream_downgrade_delay"

DEFAULT_URL: Final = "http://127.0.0.1:8090"
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_SCAN_INTERVAL: Final = 10
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 300
DEFAULT_DOWNLOAD_THRESHOLD: Final = 1.0
DEFAULT_DOWNLOAD_THRESHOLD_MBPS: Final = 0.01
DEFAULT_EXPERIMENTAL_FFPROBE: Final = False
DEFAULT_STREAM_AVERAGE_WINDOW: Final = 15
DEFAULT_STREAM_STABLE_MARGIN: Final = 0
DEFAULT_STREAM_PRELOAD_MARGIN: Final = 10
DEFAULT_STREAM_LOW_BUFFER_SECONDS: Final = 15
DEFAULT_STREAM_PROTECTED_BUFFER_SECONDS: Final = 60
DEFAULT_STREAM_DOWNGRADE_DELAY: Final = 15
MIN_STREAM_MARGIN: Final = 0
MAX_STREAM_MARGIN: Final = 300
MIN_STREAM_AVERAGE_WINDOW: Final = 5
MAX_STREAM_AVERAGE_WINDOW: Final = 300
MIN_STREAM_BUFFER_SECONDS: Final = 5
MAX_STREAM_BUFFER_SECONDS: Final = 600
MIN_STREAM_DOWNGRADE_DELAY: Final = 0
MAX_STREAM_DOWNGRADE_DELAY: Final = 120
CACHE_FULL_THRESHOLD: Final = 95.0

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
