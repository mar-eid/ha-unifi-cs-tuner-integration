"""Tests for the pure event-dispatch logic."""

from __future__ import annotations

from custom_components.cybersecurity_tuner.events import (
    BusEvent,
    cursor_after_status,
    process_events_response,
)


def test_fires_in_seq_order_with_seq_and_ts() -> None:
    """Events are sorted, prefixed and carry data + seq + ts."""
    payload = {
        "events": [
            {"seq": 43, "type": "rollback_failed", "ts": "t43", "data": {"error": "x"}},
            {
                "seq": 42,
                "type": "unknown_client_detected",
                "ts": "t42",
                "data": {"mac": "aa:bb:cc:dd:ee:ff"},
            },
        ],
        "last_seq": 43,
    }
    batch = process_events_response(payload, after=41, limit=100)
    assert batch.events == [
        BusEvent(
            "cybersecurity_tuner_unknown_client_detected",
            {"mac": "aa:bb:cc:dd:ee:ff", "seq": 42, "ts": "t42"},
        ),
        BusEvent(
            "cybersecurity_tuner_rollback_failed",
            {"error": "x", "seq": 43, "ts": "t43"},
        ),
    ]
    assert batch.last_seq == 43
    assert not batch.has_more


def test_skips_already_seen() -> None:
    """Events with seq <= after are never re-fired."""
    payload = {"events": [{"seq": 5, "type": "learning_completed", "data": {}}]}
    batch = process_events_response(payload, after=5, limit=100)
    assert batch.events == []
    assert batch.last_seq == 5


def test_malformed_entries() -> None:
    """Bad types are skipped but advance the cursor; bad seqs are ignored."""
    payload = {
        "events": [
            {"seq": "7", "type": "rollback_failed"},
            {"seq": True, "type": "rollback_failed"},
            "garbage",
            {"seq": 8, "type": "Bad-Type!"},
            {"seq": 9, "type": "x" * 60},
            {"seq": 10, "type": "future_type", "data": None},
        ]
    }
    batch = process_events_response(payload, after=6, limit=100)
    assert batch.events == [
        BusEvent("cybersecurity_tuner_future_type", {"seq": 10, "ts": None})
    ]
    assert batch.last_seq == 10


def test_seq_and_ts_override_data() -> None:
    """The envelope seq/ts win over same-named data fields."""
    payload = {
        "events": [{"seq": 2, "type": "a", "ts": "T", "data": {"seq": 99, "ts": "x"}}]
    }
    batch = process_events_response(payload, after=1, limit=100)
    assert batch.events[0].data == {"seq": 2, "ts": "T"}


def test_has_more_when_page_full() -> None:
    """A full page signals that another page may be waiting."""
    payload = {"events": [{"seq": i, "type": "a"} for i in range(1, 4)]}
    assert process_events_response(payload, after=0, limit=3).has_more
    assert not process_events_response(payload, after=0, limit=4).has_more
    # Full page of already seen events: no progress, don't loop.
    assert not process_events_response(payload, after=3, limit=3).has_more


def test_empty_and_missing_events() -> None:
    """Missing/empty events keep the cursor, regardless of last_seq."""
    assert process_events_response({}, after=4, limit=10).last_seq == 4
    assert process_events_response({"events": [], "last_seq": 0}, 4, 10).last_seq == 4
    assert process_events_response({"events": [], "last_seq": 9}, 4, 10).last_seq == 4


def test_cursor_after_status() -> None:
    """Only a status newer than the cursor can move it backwards."""
    assert cursor_after_status(50, 10, True) == 10
    assert cursor_after_status(50, 10, False) == 50
    assert cursor_after_status(50, 60, True) == 50
    assert cursor_after_status(50, None, True) == 50
    assert cursor_after_status(50, "3", True) == 50
