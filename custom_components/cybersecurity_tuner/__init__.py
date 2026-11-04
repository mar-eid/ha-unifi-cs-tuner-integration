"""The Cybersecurity Tuner integration.

Exposes status sensors for the Cybersecurity Tuner app and fires
``cybersecurity_tuner_<type>`` events for alarm automations. Firewall rule
switches are intentionally *not* provided; use the UniFi Network integration.
"""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import CybersecurityTunerClient
from .const import STORAGE_VERSION, storage_key
from .coordinator import (
    CybersecurityTunerConfigEntry,
    CybersecurityTunerCoordinator,
    CybersecurityTunerEventPoller,
    CybersecurityTunerRuntimeData,
)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: CybersecurityTunerConfigEntry
) -> bool:
    """Set up Cybersecurity Tuner from a config entry."""
    client = CybersecurityTunerClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_TOKEN],
        async_get_clientsession(hass),
    )
    coordinator = CybersecurityTunerCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    event_poller = CybersecurityTunerEventPoller(hass, entry, client, coordinator)
    await event_poller.async_initialize()

    entry.runtime_data = CybersecurityTunerRuntimeData(
        client=client, coordinator=coordinator, event_poller=event_poller
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    event_poller.async_start()
    entry.async_on_unload(event_poller.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CybersecurityTunerConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: CybersecurityTunerConfigEntry
) -> None:
    """Remove the persisted event cursor when the entry is deleted."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()


async def _async_update_listener(
    hass: HomeAssistant, entry: CybersecurityTunerConfigEntry
) -> None:
    """Reload when options (scan intervals) change."""
    await hass.config_entries.async_reload(entry.entry_id)
