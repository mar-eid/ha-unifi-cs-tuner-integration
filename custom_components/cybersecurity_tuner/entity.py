"""Base entity for Cybersecurity Tuner."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import CybersecurityTunerCoordinator


class CybersecurityTunerEntity(CoordinatorEntity[CybersecurityTunerCoordinator]):
    """Shared base: one "Cybersecurity Tuner" device per app instance."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CybersecurityTunerCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        instance_id = coordinator.config_entry.unique_id or (
            coordinator.config_entry.entry_id
        )
        self._attr_unique_id = f"{instance_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, instance_id)},
            name=NAME,
            manufacturer="mar-eid",
            model="Cybersecurity Tuner app",
            sw_version=coordinator.data.get("version"),
            entry_type=DeviceEntryType.SERVICE,
        )
