"""Status coordinator and event poller for Cybersecurity Tuner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    CybersecurityTunerAuthenticationError,
    CybersecurityTunerClient,
    CybersecurityTunerError,
)
from .const import (
    CONF_EVENTS_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_EVENTS_INTERVAL,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    EVENTS_LIMIT,
    EVENTS_MAX_PAGES,
    STORAGE_VERSION,
    storage_key,
)
from .events import cursor_after_status, process_events_response

_LOGGER = logging.getLogger(__name__)


@dataclass
class CybersecurityTunerRuntimeData:
    """Runtime data stored on the config entry."""

    client: CybersecurityTunerClient
    coordinator: CybersecurityTunerCoordinator
    event_poller: CybersecurityTunerEventPoller


type CybersecurityTunerConfigEntry = ConfigEntry[CybersecurityTunerRuntimeData]


class CybersecurityTunerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls ``/api/v1/ha/status``."""

    config_entry: CybersecurityTunerConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CybersecurityTunerConfigEntry,
        client: CybersecurityTunerClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)
            ),
        )
        self.client = client
        # time.monotonic() at which the request behind ``self.data`` was sent.
        self.status_fetched_at: float = 0.0

    async def _async_update_data(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            data = await self.client.get_status()
        except CybersecurityTunerAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CybersecurityTunerError as err:
            raise UpdateFailed(str(err)) from err
        self.status_fetched_at = started
        return data


class CybersecurityTunerEventPoller:
    """Polls ``/api/v1/ha/events`` and fires ``cybersecurity_tuner_<type>``.

    The last seen ``seq`` is persisted in a ``Store`` so a restart neither
    replays nor loses events. Delivery is at-least-once: the cursor is saved
    after the events of a page have been fired.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CybersecurityTunerConfigEntry,
        client: CybersecurityTunerClient,
        coordinator: CybersecurityTunerCoordinator,
    ) -> None:
        """Initialize the poller."""
        self._hass = hass
        self._entry = entry
        self._client = client
        self._coordinator = coordinator
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._interval = timedelta(
            seconds=entry.options.get(CONF_EVENTS_INTERVAL, DEFAULT_EVENTS_INTERVAL)
        )
        self._lock = asyncio.Lock()
        self._unsub: CALLBACK_TYPE | None = None
        self._cursor_advanced_at: float = 0.0
        self._instance_id: str | None = None
        self.last_seq: int = 0
        self.last_error: str | None = None
        self.last_poll: datetime | None = None
        self.events_fired: int = 0

    async def async_initialize(self) -> None:
        """Load the persisted cursor, falling back to ``last_event_seq``."""
        status = self._coordinator.data or {}
        self._instance_id = status.get("instance_id")
        status_seq = status.get("last_event_seq")
        if isinstance(status_seq, bool) or not isinstance(status_seq, int):
            status_seq = 0

        stored = await self._store.async_load()
        stored_seq = stored.get("last_seq") if isinstance(stored, dict) else None
        if (
            isinstance(stored, dict)
            and stored.get("instance_id") == self._instance_id
            and isinstance(stored_seq, int)
            and not isinstance(stored_seq, bool)
        ):
            # Status was fetched just now, after the stored cursor advanced.
            self.last_seq = cursor_after_status(stored_seq, status_seq, True)
            if self.last_seq != stored_seq:
                _LOGGER.warning(
                    "Event sequence of the app went backwards (%s -> %s); "
                    "resuming from %s",
                    stored_seq,
                    status_seq,
                    self.last_seq,
                )
        else:
            # First start (or a different app instance): don't replay history.
            self.last_seq = status_seq
        self._cursor_advanced_at = time.monotonic()
        await self._async_save()

    @callback
    def async_start(self) -> None:
        """Start periodic polling and do an immediate first poll."""
        self._unsub = async_track_time_interval(
            self._hass,
            self._async_scheduled_poll,
            self._interval,
            name=f"{DOMAIN} event poll",
            cancel_on_shutdown=True,
        )
        self._entry.async_create_background_task(
            self._hass, self.async_poll(), name=f"{DOMAIN} initial event poll"
        )

    @callback
    def async_stop(self) -> None:
        """Stop polling."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def _async_scheduled_poll(self, _now: datetime) -> None:
        await self.async_poll()

    async def async_poll(self) -> None:
        """Fetch new events and fire them on the bus."""
        if self._lock.locked():
            return
        async with self._lock:
            if self._check_sequence_reset():
                await self._async_save()
            for _ in range(EVENTS_MAX_PAGES):
                after = self.last_seq
                try:
                    payload = await self._client.get_events(after, EVENTS_LIMIT)
                except CybersecurityTunerError as err:
                    # A 401 here is left to the status coordinator, which
                    # raises ConfigEntryAuthFailed and starts reauth.
                    self._set_error(str(err))
                    return
                self.last_poll = dt_util.utcnow()
                if self.last_error is not None:
                    _LOGGER.info("Event polling recovered")
                    self.last_error = None

                batch = process_events_response(payload, after, EVENTS_LIMIT)
                for event in batch.events:
                    self._hass.bus.async_fire(event.event_type, event.data)
                self.events_fired += len(batch.events)
                if batch.last_seq != after:
                    self.last_seq = batch.last_seq
                    self._cursor_advanced_at = time.monotonic()
                    await self._async_save()
                if not batch.has_more:
                    return

    def _check_sequence_reset(self) -> bool:
        """Follow the app's sequence if it went backwards. Return True if reset."""
        coordinator = self._coordinator
        if not coordinator.last_update_success or not coordinator.data:
            return False
        new_seq = cursor_after_status(
            self.last_seq,
            coordinator.data.get("last_event_seq"),
            coordinator.status_fetched_at > self._cursor_advanced_at,
        )
        if new_seq != self.last_seq:
            _LOGGER.warning(
                "Event sequence of the app went backwards (%s -> %s); resetting cursor",
                self.last_seq,
                new_seq,
            )
            self.last_seq = new_seq
            self._cursor_advanced_at = time.monotonic()
            return True
        return False

    def _set_error(self, message: str) -> None:
        if self.last_error is None:
            _LOGGER.warning("Polling events failed: %s", message)
        else:
            _LOGGER.debug("Polling events failed: %s", message)
        self.last_error = message

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"instance_id": self._instance_id, "last_seq": self.last_seq}
        )
