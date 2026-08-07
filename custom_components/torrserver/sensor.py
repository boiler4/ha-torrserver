"""Sensor entities for TorrServer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TorrServerConfigEntry
from .api import TorrServerData
from .const import (
    TORRENT_ADDED,
    TORRENT_CLOSED,
    TORRENT_GETTING_INFO,
    TORRENT_IN_DB,
    TORRENT_PRELOAD,
    TORRENT_WORKING,
)
from .entity import TorrServerEntity
from .stream_health import (
    STREAM_HEALTH_OPTIONS,
    StreamHealth,
    evaluate_streams_health,
    stream_health_icon,
)

SensorValue = str | int | float | None


@dataclass(frozen=True, kw_only=True)
class TorrServerSensorEntityDescription(SensorEntityDescription):
    """Describe a TorrServer sensor."""

    value_fn: Callable[[TorrServerData], SensorValue]
    attributes_fn: Callable[[TorrServerData], dict[str, Any]] | None = None


def _active_count(data: TorrServerData) -> int:
    return len(data.active_torrents)


def _active_sum(data: TorrServerData, key: str) -> int:
    return round(data.active_sum(key))


def _bytes_per_second_to_mbps(value: Any) -> float | None:
    """Convert bytes per second to megabits per second."""
    try:
        return round(float(value) * 8 / 1_000_000, 2)
    except (TypeError, ValueError):
        return None


def _bits_per_second_to_mbps(value: Any) -> float | None:
    """Convert bits per second to megabits per second."""
    try:
        return round(float(value) / 1_000_000, 2)
    except (TypeError, ValueError):
        return None


def _current_value(data: TorrServerData, key: str) -> SensorValue:
    current = data.current_torrent
    return current.get(key) if current else None


def _stream_average_speed(data: TorrServerData) -> float:
    """Return the sum of cache-aware average speeds for active streams."""
    return sum(
        float(
            torrent.get("average_download_speed")
            if torrent.get("average_download_speed") is not None
            else torrent.get("download_speed") or 0
        )
        for torrent in data.streaming_torrents
    )


def _current_loaded_percent(data: TorrServerData) -> float | None:
    current = data.current_torrent
    if not current:
        return None
    total = float(current.get("torrent_size") or 0)
    if total <= 0:
        return None
    loaded = float(current.get("loaded_size") or 0)
    return round(min(max(loaded / total * 100, 0), 100), 1)


def _stream_health_value(data: TorrServerData) -> str:
    return evaluate_streams_health(data.streaming_torrents).state


def _stream_health_attributes(data: TorrServerData) -> dict[str, Any]:
    health = evaluate_streams_health(data.streaming_torrents)
    return {
        **health.attributes,
        "active_torrent_count": len(data.active_torrents),
        "seeding_or_idle_count": max(
            len(data.active_torrents) - len(data.streaming_torrents), 0
        ),
    }


def _current_attributes(data: TorrServerData) -> dict[str, Any]:
    current = data.current_torrent
    if not current:
        return {}
    allowed = (
        "category",
        "stat",
        "stat_string",
        "loaded_size",
        "torrent_size",
        "preloaded_bytes",
        "preload_size",
        "total_peers",
        "pending_peers",
        "active_peers",
        "connected_seeders",
        "half_open_peers",
        "duration_seconds",
    )
    attributes = {key: current[key] for key in allowed if key in current}
    if "download_speed" in current:
        attributes["download_speed_mbps"] = _bytes_per_second_to_mbps(
            current["download_speed"]
        )
    if "upload_speed" in current:
        attributes["upload_speed_mbps"] = _bytes_per_second_to_mbps(
            current["upload_speed"]
        )
    if (bit_rate_mbps := _bits_per_second_to_mbps(current.get("bit_rate"))) is not None:
        attributes["bit_rate_mbps"] = bit_rate_mbps
    return attributes


def _diagnostic_description(
    key: str,
    source_key: str,
    *,
    icon: str,
    unit: str | None = None,
) -> TorrServerSensorEntityDescription:
    """Create a disabled aggregate diagnostic sensor description."""
    return TorrServerSensorEntityDescription(
        key=key,
        translation_key=key,
        icon=icon,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _active_sum(data, source_key),
    )


SENSOR_DESCRIPTIONS: tuple[TorrServerSensorEntityDescription, ...] = (
    TorrServerSensorEntityDescription(
        key="download_speed",
        translation_key="download_speed",
        icon="mdi:download-network",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _bytes_per_second_to_mbps(
            data.active_sum("download_speed")
        ),
    ),
    TorrServerSensorEntityDescription(
        key="upload_speed",
        translation_key="upload_speed",
        icon="mdi:upload-network",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _bytes_per_second_to_mbps(
            data.active_sum("upload_speed")
        ),
    ),
    TorrServerSensorEntityDescription(
        key="stream_average_speed",
        translation_key="stream_average_speed",
        icon="mdi:chart-timeline-variant",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _bytes_per_second_to_mbps(_stream_average_speed(data)),
    ),
    TorrServerSensorEntityDescription(
        key="total_torrents",
        translation_key="total_torrents",
        icon="mdi:folder-multiple",
        value_fn=lambda data: len(data.torrents),
    ),
    TorrServerSensorEntityDescription(
        key="active_torrents",
        translation_key="active_torrents",
        icon="mdi:progress-download",
        value_fn=_active_count,
    ),
    TorrServerSensorEntityDescription(
        key="working_torrents",
        translation_key="working_torrents",
        icon="mdi:movie-open-play",
        value_fn=lambda data: data.count_state(TORRENT_WORKING),
    ),
    TorrServerSensorEntityDescription(
        key="stream_health",
        translation_key="stream_health",
        device_class=SensorDeviceClass.ENUM,
        options=STREAM_HEALTH_OPTIONS,
        value_fn=_stream_health_value,
        attributes_fn=_stream_health_attributes,
    ),
    TorrServerSensorEntityDescription(
        key="current_torrent",
        translation_key="current_torrent",
        icon="mdi:movie-open",
        value_fn=lambda data: (
            _current_value(data, "title") or _current_value(data, "name")
        ),
        attributes_fn=_current_attributes,
    ),
    TorrServerSensorEntityDescription(
        key="current_loaded_percent",
        translation_key="current_loaded_percent",
        icon="mdi:progress-check",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current_loaded_percent,
    ),
    TorrServerSensorEntityDescription(
        key="current_status",
        translation_key="current_status",
        icon="mdi:list-status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _current_value(data, "stat_string"),
    ),
    TorrServerSensorEntityDescription(
        key="added_torrents",
        translation_key="added_torrents",
        icon="mdi:plus-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.count_state(TORRENT_ADDED),
    ),
    TorrServerSensorEntityDescription(
        key="getting_info_torrents",
        translation_key="getting_info_torrents",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.count_state(TORRENT_GETTING_INFO),
    ),
    TorrServerSensorEntityDescription(
        key="preloading_torrents",
        translation_key="preloading_torrents",
        icon="mdi:download-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.count_state(TORRENT_PRELOAD),
    ),
    TorrServerSensorEntityDescription(
        key="closed_torrents",
        translation_key="closed_torrents",
        icon="mdi:close-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.count_state(TORRENT_CLOSED),
    ),
    TorrServerSensorEntityDescription(
        key="saved_torrents",
        translation_key="saved_torrents",
        icon="mdi:database",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.count_state(TORRENT_IN_DB),
    ),
    _diagnostic_description(
        "loaded_size",
        "loaded_size",
        icon="mdi:database-arrow-down",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "torrent_size",
        "torrent_size",
        icon="mdi:database",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "preloaded_bytes",
        "preloaded_bytes",
        icon="mdi:download-box",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "preload_size",
        "preload_size",
        icon="mdi:database-clock",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description("total_peers", "total_peers", icon="mdi:account-group"),
    _diagnostic_description("pending_peers", "pending_peers", icon="mdi:account-clock"),
    _diagnostic_description("active_peers", "active_peers", icon="mdi:account-network"),
    _diagnostic_description(
        "connected_seeders", "connected_seeders", icon="mdi:sprout"
    ),
    _diagnostic_description(
        "half_open_peers", "half_open_peers", icon="mdi:connection"
    ),
    _diagnostic_description(
        "bytes_written",
        "bytes_written",
        icon="mdi:database-export",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "bytes_written_data",
        "bytes_written_data",
        icon="mdi:database-export-outline",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "bytes_read",
        "bytes_read",
        icon="mdi:database-import",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "bytes_read_data",
        "bytes_read_data",
        icon="mdi:database-import-outline",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "bytes_read_useful_data",
        "bytes_read_useful_data",
        icon="mdi:database-check",
        unit=UnitOfInformation.BYTES,
    ),
    _diagnostic_description(
        "chunks_written", "chunks_written", icon="mdi:chart-box-plus-outline"
    ),
    _diagnostic_description("chunks_read", "chunks_read", icon="mdi:chart-box-outline"),
    _diagnostic_description(
        "chunks_read_useful", "chunks_read_useful", icon="mdi:check-circle-outline"
    ),
    _diagnostic_description(
        "chunks_read_wasted", "chunks_read_wasted", icon="mdi:delete-sweep-outline"
    ),
    _diagnostic_description(
        "pieces_dirtied_good", "pieces_dirtied_good", icon="mdi:check-decagram-outline"
    ),
    _diagnostic_description(
        "pieces_dirtied_bad", "pieces_dirtied_bad", icon="mdi:alert-decagram-outline"
    ),
    _diagnostic_description(
        "duration_seconds",
        "duration_seconds",
        icon="mdi:timer-outline",
        unit=UnitOfTime.SECONDS,
    ),
    TorrServerSensorEntityDescription(
        key="current_bit_rate",
        translation_key="current_bit_rate",
        icon="mdi:speedometer",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _bits_per_second_to_mbps(
            _current_value(data, "bit_rate")
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TorrServerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TorrServer sensors."""
    async_add_entities(
        TorrServerSensor(entry, description) for description in SENSOR_DESCRIPTIONS
    )


class TorrServerSensor(TorrServerEntity, SensorEntity):
    """Representation of a TorrServer sensor."""

    entity_description: TorrServerSensorEntityDescription

    def __init__(
        self,
        entry: TorrServerConfigEntry,
        description: TorrServerSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> SensorValue:
        """Return the current sensor value."""
        if self.entity_description.key == "stream_health":
            return self._stream_health().state
        return self.entity_description.value_fn(self.coordinator.data)

    def _stream_health(self) -> StreamHealth:
        """Evaluate streaming health with the configured speed margins."""
        return evaluate_streams_health(
            self.coordinator.data.streaming_torrents,
            yellow_margin_percent=self.coordinator.stream_yellow_margin,
            green_margin_percent=self.coordinator.stream_green_margin,
        )

    @property
    def icon(self) -> str | None:
        """Return a state-aware icon for streaming health."""
        if self.entity_description.key == "stream_health":
            return stream_health_icon(str(self.native_value))
        return self.entity_description.icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return limited attributes for the current torrent sensor."""
        if self.entity_description.key == "stream_health":
            health = self._stream_health()
            return {
                **health.attributes,
                "active_torrent_count": len(self.coordinator.data.active_torrents),
                "seeding_or_idle_count": max(
                    len(self.coordinator.data.active_torrents)
                    - len(self.coordinator.data.streaming_torrents),
                    0,
                ),
            }
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
