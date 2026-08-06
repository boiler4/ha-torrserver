"""Shared entity support for TorrServer."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TorrServerConfigEntry
from .const import DOMAIN
from .coordinator import TorrServerDataUpdateCoordinator


class TorrServerEntity(CoordinatorEntity[TorrServerDataUpdateCoordinator]):
    """Base class for TorrServer entities."""

    _attr_has_entity_name = True

    def __init__(self, entry: TorrServerConfigEntry, key: str) -> None:
        """Initialize a TorrServer entity."""
        super().__init__(entry.runtime_data)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_suggested_object_id = f"torrserver_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return TorrServer device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            manufacturer="YouROK",
            model="TorrServer",
            name=self._entry.title,
            sw_version=self.coordinator.data.version if self.coordinator.data else None,
            configuration_url=self.coordinator.client.base_url,
        )
