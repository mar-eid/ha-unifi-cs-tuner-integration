"""Diagnostics for Cybersecurity Tuner."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import CybersecurityTunerConfigEntry

TO_REDACT = {CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CybersecurityTunerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    poller = runtime.event_poller
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "status": async_redact_data(runtime.coordinator.data or {}, TO_REDACT),
        "last_update_success": runtime.coordinator.last_update_success,
        "event_poller": {
            "last_seq": poller.last_seq,
            "last_poll": poller.last_poll.isoformat() if poller.last_poll else None,
            "last_error": poller.last_error,
            "events_fired": poller.events_fired,
        },
    }
