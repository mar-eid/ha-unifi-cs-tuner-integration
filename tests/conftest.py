"""Shared fixtures for Cybersecurity Tuner tests."""

from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cybersecurity_tuner.const import DOMAIN

INSTANCE_ID = "3f2c0000-test-instance"

STATUS: dict[str, Any] = {
    "api_version": 1,
    "healthy": True,
    "version": "0.1.0",
    "instance_id": INSTANCE_ID,
    "syslog": {
        "mode": "embedded",
        "healthy": True,
        "received": 12345,
        "invalid": 2,
        "dropped": 0,
        "last_message_at": "2026-11-04T12:00:00Z",
    },
    "unifi": {"connected": True, "last_sync": "2026-11-04T11:59:30Z", "error": None},
    "learning_active": False,
    "temporary_exception_active": True,
    "temporary_exceptions": [
        {
            "id": 3,
            "rule_id": "abc",
            "rule_name": "Block IoT",
            "expires_at": "2026-11-04T12:30:00Z",
        }
    ],
    "unknown_devices": 2,
    "blocked_events_1h": 57,
    "last_capture_status": "completed",
    "last_capture_at": "2026-11-04T10:00:00Z",
    "last_event_seq": 41,
}

ENTRY_DATA = {
    CONF_HOST: "local-cybersecurity-tuner",
    CONF_PORT: 8099,
    CONF_TOKEN: "secret-token",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""


@pytest.fixture
def status() -> dict[str, Any]:
    """Return a fresh copy of the status payload."""
    return deepcopy(STATUS)


@pytest.fixture
def mock_client(status: dict[str, Any]) -> Generator[tuple[AsyncMock, AsyncMock]]:
    """Patch the API client's methods. Yields (get_status, get_events)."""
    with (
        patch(
            "custom_components.cybersecurity_tuner.api.CybersecurityTunerClient.get_status",
            new_callable=AsyncMock,
            return_value=status,
        ) as get_status,
        patch(
            "custom_components.cybersecurity_tuner.api.CybersecurityTunerClient.get_events",
            new_callable=AsyncMock,
            return_value={"events": [], "last_seq": 41},
        ) as get_events,
    ):
        yield get_status, get_events


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for the integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Cybersecurity Tuner",
        data=dict(ENTRY_DATA),
        unique_id=INSTANCE_ID,
    )
