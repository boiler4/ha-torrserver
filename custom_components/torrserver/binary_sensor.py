"""Binary sensor entities for TorrServer."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TorrServerConfigEntry
from .const import (
    CONF_DOWNLOAD_THRESHOLD,
    CONF_DOWNLOAD_THRESHOLD_MBPS,
    DEFAULT_DOWNLOAD_THRESHOLD,
    DEFAULT_DOWNLOAD_THRESHOLD_MBPS,
    TORRENT_WORKING,
)
from .entity import TorrServerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TorrServerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TorrServer binary sensors."""
    async_add_entities(
        (
            TorrServerConnectedBinarySensor(entry),
            TorrServerDownloadingBinarySensor(entry),
            TorrServerWorkingBinarySensor(entry),
            TorrServerStreamInterruptionRiskBinarySensor(entry),
        )
    )


class TorrServerBinarySensor(TorrServerEntity, BinarySensorEntity):
    """Base class for TorrServer binary sensors."""

    def __init__(
        self,
        entry: TorrServerConfigEntry,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(entry, description.key)
        self.entity_description = description


class TorrServerConnectedBinarySensor(TorrServerBinarySensor):
    """Show whether the most recent TorrServer request succeeded."""

    def __init__(self, entry: TorrServerConfigEntry) -> None:
        """Initialize connectivity."""
        super().__init__(
            entry,
            BinarySensorEntityDescription(
                key="connected",
                translation_key="connected",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
        )

    @property
    def available(self) -> bool:
        """Keep connectivity visible even when the server is offline."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the latest coordinator update succeeded."""
        return self.coordinator.last_update_success


class TorrServerDownloadingBinarySensor(TorrServerBinarySensor):
    """Show whether TorrServer is currently downloading."""

    def __init__(self, entry: TorrServerConfigEntry) -> None:
        """Initialize the downloading sensor."""
        super().__init__(
            entry,
            BinarySensorEntityDescription(
                key="downloading",
                translation_key="downloading",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
        )

    @property
    def is_on(self) -> bool:
        """Return whether aggregate download speed exceeds the threshold."""
        if CONF_DOWNLOAD_THRESHOLD_MBPS in self._entry.options:
            threshold = (
                float(
                    self._entry.options.get(
                        CONF_DOWNLOAD_THRESHOLD_MBPS,
                        DEFAULT_DOWNLOAD_THRESHOLD_MBPS,
                    )
                )
                * 1_000_000
                / 8
            )
        else:
            # Compatibility with beta entries that stored this value in B/s.
            threshold = float(
                self._entry.options.get(
                    CONF_DOWNLOAD_THRESHOLD, DEFAULT_DOWNLOAD_THRESHOLD
                )
            )
        return self.coordinator.data.active_sum("download_speed") > threshold


class TorrServerWorkingBinarySensor(TorrServerBinarySensor):
    """Show whether TorrServer reports any working torrent."""

    def __init__(self, entry: TorrServerConfigEntry) -> None:
        """Initialize the working sensor."""
        super().__init__(
            entry,
            BinarySensorEntityDescription(
                key="working",
                translation_key="working",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
        )

    @property
    def is_on(self) -> bool:
        """Return whether TorrServer has a torrent in the working state."""
        return self.coordinator.data.count_state(TORRENT_WORKING) > 0


class TorrServerStreamInterruptionRiskBinarySensor(TorrServerBinarySensor):
    """Show a confirmed risk of interruption for any active stream."""

    def __init__(self, entry: TorrServerConfigEntry) -> None:
        """Initialize the interruption-risk sensor."""
        super().__init__(
            entry,
            BinarySensorEntityDescription(
                key="stream_interruption_risk",
                translation_key="stream_interruption_risk",
                device_class=BinarySensorDeviceClass.PROBLEM,
            ),
        )

    @property
    def is_on(self) -> bool:
        """Return whether any active reader has a confirmed interruption risk."""
        return any(
            bool(torrent.get("stream_interruption_risk"))
            for torrent in self.coordinator.data.streaming_torrents
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose only aggregate, explainable risk details."""
        streams = self.coordinator.data.streaming_torrents
        eta_values = [
            float(torrent["stream_interruption_eta_seconds"])
            for torrent in streams
            if torrent.get("stream_interruption_eta_seconds") is not None
        ]
        return {
            "stream_count": len(streams),
            "at_risk_streams": sum(
                bool(torrent.get("stream_interruption_risk"))
                for torrent in streams
            ),
            "minimum_eta_seconds": min(eta_values) if eta_values else None,
            "risk_horizon_seconds": self.coordinator.stream_risk_horizon,
            "confirmation_seconds": self.coordinator.stream_risk_confirmation,
        }
