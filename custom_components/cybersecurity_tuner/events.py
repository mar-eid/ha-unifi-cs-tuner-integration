"""Pure event-dispatch logic (no Home Assistant imports).

Turns an ``/api/v1/ha/events`` response into the list of HA bus events to
fire and the new cursor (last seen ``seq``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import re
from typing import Any

from .const import EVENT_PREFIX

_LOGGER = logging.getLogger(__name__)

# Home Assistant limits event_type to 64 characters.
MAX_EVENT_TYPE_LENGTH = 64
_TYPE_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True, slots=True)
class BusEvent:
    """An event to fire on the Home Assistant event bus."""

    event_type: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EventBatch:
    """Result of processing one events response."""

    events: list[BusEvent] = field(default_factory=list)
    last_seq: int = 0
    # True when the page was full, so another page may be waiting.
    has_more: bool = False


def _as_seq(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def bus_event_type(event_type: Any) -> str | None:
    """Return the HA event type for an app event type, or None if invalid."""
    if not isinstance(event_type, str) or not _TYPE_RE.match(event_type):
        return None
    full = f"{EVENT_PREFIX}{event_type}"
    if len(full) > MAX_EVENT_TYPE_LENGTH:
        return None
    return full


def process_events_response(
    payload: Mapping[str, Any], after: int, limit: int
) -> EventBatch:
    """Build bus events from an events response.

    - Events with ``seq <= after`` are ignored (no replay / duplicates).
    - Events are fired in ``seq`` order with ``data`` + ``seq`` + ``ts``.
    - Unknown but well-formed types are forwarded (forward compatible);
      malformed entries are skipped but still advance the cursor.
    - The response's top-level ``last_seq`` is not needed: the cursor is the
      highest ``seq`` actually received.
    """
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raw_events = []

    valid: list[tuple[int, Mapping[str, Any]]] = []
    for raw in raw_events:
        if not isinstance(raw, Mapping):
            continue
        seq = _as_seq(raw.get("seq"))
        if seq is None:
            _LOGGER.debug("Ignoring event without valid seq: %s", raw)
            continue
        if seq > after:
            valid.append((seq, raw))
    valid.sort(key=lambda item: item[0])

    bus_events: list[BusEvent] = []
    last_seq = after
    for seq, raw in valid:
        last_seq = seq
        event_type = bus_event_type(raw.get("type"))
        if event_type is None:
            _LOGGER.warning(
                "Ignoring event %s with invalid type %r", seq, raw.get("type")
            )
            continue
        data = raw.get("data")
        event_data: dict[str, Any] = dict(data) if isinstance(data, Mapping) else {}
        event_data["seq"] = seq
        event_data["ts"] = raw.get("ts")
        bus_events.append(BusEvent(event_type, event_data))

    has_more = len(raw_events) >= limit and last_seq > after
    return EventBatch(events=bus_events, last_seq=last_seq, has_more=has_more)


def cursor_after_status(
    cursor: int, status_last_seq: Any, status_is_newer_than_cursor: bool
) -> int:
    """Return the cursor to use given a fresh ``/status`` ``last_event_seq``.

    If a status fetched *after* the cursor last advanced reports a lower
    ``last_event_seq``, the app's sequence went backwards (event log reset);
    follow it so new events are not silently skipped. A status fetched before
    the cursor advanced may legitimately be behind and is ignored.
    """
    status_seq = _as_seq(status_last_seq)
    if status_seq is None or not status_is_newer_than_cursor:
        return cursor
    return status_seq if status_seq < cursor else cursor
