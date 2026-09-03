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
from .stream_forecast import (
    STREAM_FORECAST_OPTIONS,
    StreamForecast,
    evaluate_streams_forecast,
    stream_forecast_icon,
)
from .stream_health import (
    STREAM_BUFFER_MODE_OPTIONS,
    STREAM_HEALTH_OPTIONS,
    StreamHealth,
    evaluate_stream_health,
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


def _stream_buffer_seconds(data: TorrServerData) -> float | None:
    """Return the least protected active reader buffer in seconds."""
    values = [
        float(torrent["buffer_seconds"])
        for torrent in data.streaming_torrents
        if torrent.get("buffer_seconds") is not None
    ]
    return round(min(values), 1) if values else None


def _stream_buffer_mode(data: TorrServerData) -> str:
    """Return the shared buffer mode or mark simultaneous mixed modes."""
    modes = {
        str(torrent.get("buffer_mode") or "unknown")
        for torrent in data.streaming_torrents
    }
    if not modes:
        return "idle"
    if len(modes) > 1:
        return "multiple"
    return modes.pop()


def _stream_annotation_values(data: TorrServerData, key: str) -> list[float]:
    """Return numeric forecast annotations for active streams."""
    values: list[float] = []
    for torrent in data.streaming_torrents:
        value = torrent.get(key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _stream_minimum(data: TorrServerData, key: str) -> float | None:
    values = _stream_annotation_values(data, key)
    return round(min(values), 1) if values else None


def _stream_maximum(data: TorrServerData, key: str) -> float | None:
    values = _stream_annotation_values(data, key)
    return round(max(values), 1) if values else None


def _stream_total(data: TorrServerData, key: str) -> float | None:
    values = _stream_annotation_values(data, key)
    return round(sum(values), 2) if values else None


def _current_loaded_percent(data: TorrServerData) -> float | None:
    current = data.current_torrent
    if not current:
        return None
    total = float(current.get("torrent_size") or 0)
    if total <= 0:
        return None
    loaded = float(current.get("loaded_size") or 0)
    return round(min(max(loaded / total * 100, 0), 100), 1)


def _current_bit_rate_health(data: TorrServerData) -> StreamHealth | None:
    """Return the same bitrate assessment used by stream health."""
    current = data.current_torrent
    return evaluate_stream_health(current) if current else None


def _current_bit_rate(data: TorrServerData) -> float | None:
    health = _current_bit_rate_health(data)
    if health is None:
        return None
    value = health.attributes.get("bit_rate_mbps")
    return float(value) if value is not None else None


def _current_bit_rate_attributes(data: TorrServerData) -> dict[str, Any]:
    health = _current_bit_rate_health(data)
    if health is None:
        return {}
    current = data.current_torrent or {}
    return {
        "bit_rate_source": health.attributes.get("bit_rate_source"),
        "estimated": health.attributes.get("bit_rate_estimated", True),
        "ffprobe_status": current.get("ffprobe_status", data.ffprobe_status),
        "ffprobe_failure_count": current.get(
            "ffprobe_failure_count", data.ffprobe_failures
        ),
        "ffprobe_last_error": current.get(
            "ffprobe_last_error", data.ffprobe_last_error
        ),
        "ffprobe_retry_seconds": current.get(
            "ffprobe_retry_seconds", data.ffprobe_retry_seconds
        ),
    }


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
        "active_file_size",
        "bit_rate_source",
        "bit_rate_estimated",
        "ffprobe_status",
        "ffprobe_failure_count",
        "ffprobe_last_error",
        "ffprobe_retry_seconds",
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
        key="stream_buffer_seconds",
        translation_key="stream_buffer_seconds",
        icon="mdi:timer-play-outline",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_stream_buffer_seconds,
    ),
    TorrServerSensorEntityDescription(
        key="stream_buffer_mode",
        translation_key="stream_buffer_mode",
        icon="mdi:buffer",
        device_class=SensorDeviceClass.ENUM,
        options=STREAM_BUFFER_MODE_OPTIONS,
        value_fn=_stream_buffer_mode,
    ),
    TorrServerSensorEntityDescription(
        key="stream_forecast",
        translation_key="stream_forecast",
        device_class=SensorDeviceClass.ENUM,
        options=STREAM_FORECAST_OPTIONS,
        value_fn=lambda data: evaluate_streams_forecast(data.streaming_torrents).state,
    ),
    TorrServerSensorEntityDescription(
        key="stream_interruption_eta",
        translation_key="stream_interruption_eta",
        icon="mdi:timer-alert-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _stream_minimum(data, "stream_interruption_eta_seconds"),
    ),
    TorrServerSensorEntityDescription(
        key="stream_speed_margin",
        translation_key="stream_speed_margin",
        icon="mdi:speedometer-medium",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _stream_minimum(data, "stream_speed_margin_percent"),
    ),
    TorrServerSensorEntityDescription(
        key="stream_session_minimum_buffer",
        translation_key="stream_session_minimum_buffer",
        icon="mdi:timer-minus-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _stream_minimum(
            data, "stream_session_minimum_buffer_seconds"
        ),
    ),
    TorrServerSensorEntityDescription(
        key="stream_session_average_speed",
        translation_key="stream_session_average_speed",
        icon="mdi:chart-line",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _stream_total(data, "stream_session_average_speed_mbps"),
    ),
    TorrServerSensorEntityDescription(
        key="stream_session_insufficient_time",
        translation_key="stream_session_insufficient_time",
        icon="mdi:timer-alert",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _stream_maximum(
            data, "stream_session_insufficient_seconds"
        ),
    ),
    TorrServerSensorEntityDescription(
        key="stream_session_risk_events",
        translation_key="stream_session_risk_events",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _stream_total(data, "stream_session_risk_events"),
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
        value_fn=_current_bit_rate,
        attributes_fn=_current_bit_rate_attributes,
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
        if self.entity_description.key == "stream_forecast":
            return self._stream_forecast().state
        return self.entity_description.value_fn(self.coordinator.data)

    def _stream_health(self) -> StreamHealth:
        """Evaluate buffer-first health with the configured thresholds."""
        return evaluate_streams_health(
            self.coordinator.data.streaming_torrents,
            stable_margin_percent=self.coordinator.stream_stable_margin,
            preload_margin_percent=self.coordinator.stream_preload_margin,
            low_buffer_seconds=self.coordinator.stream_low_buffer_seconds,
            protected_buffer_seconds=(self.coordinator.stream_protected_buffer_seconds),
        )

    def _stream_forecast(self) -> StreamForecast:
        """Evaluate interruption risk with the configured thresholds."""
        return evaluate_streams_forecast(
            self.coordinator.data.streaming_torrents,
            risk_horizon_seconds=self.coordinator.stream_risk_horizon,
            stable_margin_percent=self.coordinator.stream_stable_margin,
            preload_margin_percent=self.coordinator.stream_preload_margin,
            low_buffer_seconds=self.coordinator.stream_low_buffer_seconds,
            protected_buffer_seconds=(self.coordinator.stream_protected_buffer_seconds),
        )

    @property
    def icon(self) -> str | None:
        """Return a state-aware icon for streaming health."""
        if self.entity_description.key == "stream_health":
            return stream_health_icon(str(self.native_value))
        if self.entity_description.key == "stream_forecast":
            return stream_forecast_icon(str(self.native_value))
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
        if self.entity_description.key == "stream_forecast":
            return self._stream_forecast().attributes
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
