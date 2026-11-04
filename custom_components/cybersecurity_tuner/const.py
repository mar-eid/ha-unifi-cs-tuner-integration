"""Constants for the Cybersecurity Tuner integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "cybersecurity_tuner"
NAME: Final = "Cybersecurity Tuner"

DEFAULT_PORT: Final = 8099

CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_EVENTS_INTERVAL: Final = "events_interval"

DEFAULT_STATUS_INTERVAL: Final = 30  # seconds
DEFAULT_EVENTS_INTERVAL: Final = 10  # seconds
MIN_STATUS_INTERVAL: Final = 10
MIN_EVENTS_INTERVAL: Final = 5
MAX_INTERVAL: Final = 3600

# Integration API contract (docs/ha-api.md in the app repository).
API_VERSION: Final = 1
STATUS_PATH: Final = "/api/v1/ha/status"
EVENTS_PATH: Final = "/api/v1/ha/events"
EVENTS_LIMIT: Final = 100
# Max pages fetched back-to-back in one poll when draining a backlog.
EVENTS_MAX_PAGES: Final = 10
REQUEST_TIMEOUT: Final = 10  # seconds

# Fired on the HA event bus as f"{EVENT_PREFIX}{type}".
EVENT_PREFIX: Final = f"{DOMAIN}_"

EVENT_TYPES: Final = (
    "unknown_client_detected",
    "suspected_security_incident",
    "learning_completed",
    "rule_change_detected",
    "temporary_exception_expiring",
    "rollback_failed",
)

CAPTURE_STATUSES: Final = ["none", "running", "completed", "failed", "stopped"]

STORAGE_VERSION: Final = 1


def storage_key(entry_id: str) -> str:
    """Return the Store key that holds the event cursor for a config entry."""
    return f"{DOMAIN}.{entry_id}"
