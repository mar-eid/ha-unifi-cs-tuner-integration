"""Tests for setup, entities, the event poller and diagnostics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.cybersecurity_tuner.api import (
    CybersecurityTunerAuthenticationError,
    CybersecurityTunerConnectionError,
)
from custom_components.cybersecurity_tuner.const import DOMAIN, storage_key
from custom_components.cybersecurity_tuner.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import INSTANCE_ID

EVENTS = {
    "events": [
        {
            "seq": 42,
            "type": "unknown_client_detected",
            "ts": "2026-11-04T12:00:05Z",
            "data": {"mac": "aa:bb:cc:dd:ee:ff", "ip": "10.0.2.51"},
        },
        {
            "seq": 43,
            "type": "rollback_failed",
            "ts": "2026-11-04T12:00:06Z",
            "data": {"id": 3, "rule_id": "abc", "error": "boom"},
        },
    ],
    "last_seq": 43,
}


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities(
    hass: HomeAssistant,
    mock_client,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """All six entities are created with the expected ids and states."""
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    healthy = hass.states.get("binary_sensor.cybersecurity_tuner_healthy")
    assert healthy.state == STATE_ON
    assert "device_class" not in healthy.attributes
    assert healthy.attributes["syslog_mode"] == "embedded"
    assert healthy.attributes["syslog_received"] == 12345
    assert healthy.attributes["unifi_connected"] is True
    assert healthy.attributes["unifi_error"] is None

    assert (
        hass.states.get("binary_sensor.cybersecurity_tuner_learning_active").state
        == STATE_OFF
    )
    temp = hass.states.get(
        "binary_sensor.cybersecurity_tuner_temporary_exception_active"
    )
    assert temp.state == STATE_ON
    assert temp.attributes["temporary_exceptions"][0]["rule_name"] == "Block IoT"

    unknown = hass.states.get("sensor.cybersecurity_tuner_unknown_devices")
    assert unknown.state == "2"
    assert unknown.attributes["state_class"] == "measurement"
    assert hass.states.get("sensor.cybersecurity_tuner_blocked_events_1h").state == "57"

    capture = hass.states.get("sensor.cybersecurity_tuner_last_capture_status")
    assert capture.state == "completed"
    assert capture.attributes["device_class"] == "enum"
    assert capture.attributes["options"] == [
        "none",
        "running",
        "completed",
        "failed",
        "stopped",
    ]
    assert capture.attributes["last_capture_at"] == "2026-11-04T10:00:00Z"

    entries = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    assert len(entries) == 6
    assert {e.unique_id for e in entries} >= {f"{INSTANCE_ID}_healthy"}
    # No switch platform: firewall rules belong to the UniFi Network integration.
    assert not hass.states.async_entity_ids("switch")


async def test_unknown_capture_status(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry, status: dict
) -> None:
    """Unexpected enum values become unknown instead of crashing."""
    status["last_capture_status"] = "weird"
    await _setup(hass, config_entry)
    assert (
        hass.states.get("sensor.cybersecurity_tuner_last_capture_status").state
        == "unknown"
    )


async def test_events_fired_and_cursor_persisted(
    hass: HomeAssistant,
    mock_client,
    config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """New events are fired once, with data + seq + ts, and the cursor saved."""
    _, get_events = mock_client
    get_events.return_value = EVENTS
    unknown = async_capture_events(hass, "cybersecurity_tuner_unknown_client_detected")
    rollback = async_capture_events(hass, "cybersecurity_tuner_rollback_failed")

    await _setup(hass, config_entry)

    # First poll starts at last_event_seq from /status.
    assert get_events.await_args_list[0].args == (41, 100)
    assert len(unknown) == 1
    assert unknown[0].data == {
        "mac": "aa:bb:cc:dd:ee:ff",
        "ip": "10.0.2.51",
        "seq": 42,
        "ts": "2026-11-04T12:00:05Z",
    }
    assert rollback[0].data["error"] == "boom"
    assert rollback[0].data["seq"] == 43
    stored = hass_storage[storage_key(config_entry.entry_id)]["data"]
    assert stored == {"instance_id": INSTANCE_ID, "last_seq": 43}

    # Next scheduled poll continues after 43 and does not re-fire.
    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert get_events.await_args_list[-1].args == (43, 100)
    assert len(unknown) == 1
    assert len(rollback) == 1


async def test_backlog_drained_in_pages(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """A full page triggers an immediate follow-up request."""
    _, get_events = mock_client
    page = {"events": [{"seq": 41 + i, "type": "a"} for i in range(1, 101)]}
    get_events.side_effect = [page, {"events": [{"seq": 142, "type": "a"}]}]
    fired = async_capture_events(hass, "cybersecurity_tuner_a")
    await _setup(hass, config_entry)
    assert [c.args for c in get_events.await_args_list] == [(41, 100), (141, 100)]
    assert len(fired) == 101


async def test_restart_resumes_from_store(
    hass: HomeAssistant,
    mock_client,
    config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """After a restart polling resumes from the persisted seq (no loss)."""
    hass_storage[storage_key(config_entry.entry_id)] = {
        "version": 1,
        "minor_version": 1,
        "key": storage_key(config_entry.entry_id),
        "data": {"instance_id": INSTANCE_ID, "last_seq": 38},
    }
    _, get_events = mock_client
    await _setup(hass, config_entry)
    assert get_events.await_args_list[0].args == (38, 100)


async def test_stored_seq_ahead_of_app_is_reset(
    hass: HomeAssistant,
    mock_client,
    config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """If the app's sequence went backwards, follow it."""
    hass_storage[storage_key(config_entry.entry_id)] = {
        "version": 1,
        "minor_version": 1,
        "key": storage_key(config_entry.entry_id),
        "data": {"instance_id": INSTANCE_ID, "last_seq": 500},
    }
    _, get_events = mock_client
    await _setup(hass, config_entry)
    assert get_events.await_args_list[0].args == (41, 100)


async def test_runtime_sequence_reset(
    hass: HomeAssistant,
    mock_client,
    config_entry: MockConfigEntry,
    status: dict,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A status fetched after the cursor advanced may move it backwards."""
    get_status, get_events = mock_client
    get_events.return_value = EVENTS
    await _setup(hass, config_entry)
    assert config_entry.runtime_data.event_poller.last_seq == 43

    # App database wiped: sequence restarts.
    get_events.return_value = {"events": [], "last_seq": 0}
    get_status.return_value = {**status, "last_event_seq": 2}
    for _ in range(4):  # status refresh at +30 s, then the next event poll
        freezer.tick(timedelta(seconds=10))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert config_entry.runtime_data.event_poller.last_seq == 2
    assert get_events.await_args_list[-1].args == (2, 100)


async def test_unavailable_when_app_unreachable(
    hass: HomeAssistant,
    mock_client,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """All entities become unavailable when /status fails."""
    get_status, get_events = mock_client
    await _setup(hass, config_entry)
    get_status.side_effect = CybersecurityTunerConnectionError
    get_events.side_effect = CybersecurityTunerConnectionError
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    for entity_id in (
        "binary_sensor.cybersecurity_tuner_healthy",
        "sensor.cybersecurity_tuner_unknown_devices",
    ):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert config_entry.runtime_data.event_poller.last_error is not None


async def test_setup_retry_when_unreachable(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """Setup is retried if the app is not reachable."""
    mock_client[0].side_effect = CybersecurityTunerConnectionError
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """A 401 starts the reauth flow."""
    mock_client[0].side_effect = CybersecurityTunerAuthenticationError
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == SOURCE_REAUTH for flow in flows)


async def test_unload_and_remove(
    hass: HomeAssistant,
    mock_client,
    config_entry: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    """Unloading stops polling; removing deletes the stored cursor."""
    await _setup(hass, config_entry)
    assert storage_key(config_entry.entry_id) in hass_storage
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert storage_key(config_entry.entry_id) not in hass_storage


async def test_options_reload(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """Changing options reloads the entry with the new interval."""
    await _setup(hass, config_entry)
    hass.config_entries.async_update_entry(
        config_entry, options={"status_interval": 60}
    )
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.coordinator.update_interval == timedelta(
        seconds=60
    )


async def test_diagnostics_redacts_token(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """The token never appears in diagnostics."""
    await _setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    assert "secret-token" not in str(diag)
    assert diag["status"]["instance_id"] == INSTANCE_ID
    assert diag["event_poller"]["last_seq"] == 41
    assert DOMAIN == diag["entry"]["domain"]
