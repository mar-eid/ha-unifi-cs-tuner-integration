"""Binary sensors for Cybersecurity Tuner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CybersecurityTunerConfigEntry
from .entity import CybersecurityTunerEntity

PARALLEL_UPDATES = 0


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _health_attributes(data: dict[str, Any]) -> dict[str, Any]:
    syslog = _section(data, "syslog")
    unifi = _section(data, "unifi")
    return {
        "syslog_mode": syslog.get("mode"),
        "syslog_healthy": syslog.get("healthy"),
        "syslog_received": syslog.get("received"),
        "syslog_invalid": syslog.get("invalid"),
        "syslog_dropped": syslog.get("dropped"),
        "syslog_last_message_at": syslog.get("last_message_at"),
        "unifi_connected": unifi.get("connected"),
        "unifi_last_sync": unifi.get("last_sync"),
        "unifi_error": unifi.get("error"),
    }


def _temporary_exceptions(data: dict[str, Any]) -> dict[str, Any]:
    exceptions = data.get("temporary_exceptions")
    return {"temporary_exceptions": exceptions if isinstance(exceptions, list) else []}


@dataclass(frozen=True, kw_only=True)
class CybersecurityTunerBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Cybersecurity Tuner binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool | None]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _bool(key: str) -> Callable[[dict[str, Any]], bool | None]:
    def value(data: dict[str, Any]) -> bool | None:
        raw = data.get(key)
        return raw if isinstance(raw, bool) else None

    return value


BINARY_SENSORS: tuple[CybersecurityTunerBinarySensorEntityDescription, ...] = (
    # No device class on purpose: on = healthy (device class "problem" would
    # invert the meaning).
    CybersecurityTunerBinarySensorEntityDescription(
        key="healthy",
        translation_key="healthy",
        value_fn=_bool("healthy"),
        attributes_fn=_health_attributes,
    ),
    CybersecurityTunerBinarySensorEntityDescription(
        key="learning_active",
        translation_key="learning_active",
        value_fn=_bool("learning_active"),
    ),
    CybersecurityTunerBinarySensorEntityDescription(
        key="temporary_exception_active",
        translation_key="temporary_exception_active",
        value_fn=_bool("temporary_exception_active"),
        attributes_fn=_temporary_exceptions,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CybersecurityTunerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        CybersecurityTunerBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class CybersecurityTunerBinarySensor(CybersecurityTunerEntity, BinarySensorEntity):
    """A Cybersecurity Tuner binary sensor."""

    entity_description: CybersecurityTunerBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
