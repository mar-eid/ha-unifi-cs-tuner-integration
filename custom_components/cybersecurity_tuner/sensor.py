"""Sensors for Cybersecurity Tuner."""

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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import CAPTURE_STATUSES
from .coordinator import CybersecurityTunerConfigEntry
from .entity import CybersecurityTunerEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CybersecurityTunerSensorEntityDescription(SensorEntityDescription):
    """Describes a Cybersecurity Tuner sensor."""

    value_fn: Callable[[dict[str, Any]], StateType]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _count(key: str) -> Callable[[dict[str, Any]], StateType]:
    def value(data: dict[str, Any]) -> StateType:
        raw = data.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int):
            return None
        return raw

    return value


def _capture_status(data: dict[str, Any]) -> StateType:
    raw = data.get("last_capture_status")
    return raw if raw in CAPTURE_STATUSES else None


SENSORS: tuple[CybersecurityTunerSensorEntityDescription, ...] = (
    CybersecurityTunerSensorEntityDescription(
        key="unknown_devices",
        translation_key="unknown_devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count("unknown_devices"),
    ),
    CybersecurityTunerSensorEntityDescription(
        key="blocked_events_1h",
        translation_key="blocked_events_1h",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count("blocked_events_1h"),
    ),
    CybersecurityTunerSensorEntityDescription(
        key="last_capture_status",
        translation_key="last_capture_status",
        device_class=SensorDeviceClass.ENUM,
        options=CAPTURE_STATUSES,
        value_fn=_capture_status,
        attributes_fn=lambda data: {"last_capture_at": data.get("last_capture_at")},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CybersecurityTunerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        CybersecurityTunerSensor(coordinator, description) for description in SENSORS
    )


class CybersecurityTunerSensor(CybersecurityTunerEntity, SensorEntity):
    """A Cybersecurity Tuner sensor."""

    entity_description: CybersecurityTunerSensorEntityDescription

    @property
    def native_value(self) -> StateType:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
