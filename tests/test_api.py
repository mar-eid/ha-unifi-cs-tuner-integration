"""Tests for the API client against a real aiohttp test server."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from custom_components.cybersecurity_tuner.api import (
    CybersecurityTunerAuthenticationError,
    CybersecurityTunerClient,
    CybersecurityTunerConnectionError,
    CybersecurityTunerResponseError,
)

# The HA test plugin blocks sockets; these tests use a real local server.
pytestmark = pytest.mark.usefixtures("socket_enabled")

TOKEN = "s3cret"


async def _client_for(
    handler: Any, path: str, *, request_timeout: float = 5
) -> tuple[TestServer, aiohttp.ClientSession, CybersecurityTunerClient]:
    app = web.Application()
    app.router.add_get(path, handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    session = aiohttp.ClientSession()
    client = CybersecurityTunerClient(
        "127.0.0.1", server.port, TOKEN, session, request_timeout=request_timeout
    )
    return server, session, client


async def _close(server: TestServer, session: aiohttp.ClientSession) -> None:
    await session.close()
    await server.close()


async def test_get_status_sends_bearer_token() -> None:
    """Status is fetched with the Authorization header."""
    seen: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return web.json_response({"instance_id": "abc", "last_event_seq": 4})

    server, session, client = await _client_for(handler, "/api/v1/ha/status")
    try:
        assert await client.get_status() == {"instance_id": "abc", "last_event_seq": 4}
        assert seen["auth"] == f"Bearer {TOKEN}"
    finally:
        await _close(server, session)


async def test_get_events_passes_query() -> None:
    """Events are fetched with after/limit."""
    seen: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        seen.update(request.query)
        return web.json_response({"events": [], "last_seq": 7})

    server, session, client = await _client_for(handler, "/api/v1/ha/events")
    try:
        assert await client.get_events(7, 50) == {"events": [], "last_seq": 7}
        assert seen == {"after": "7", "limit": "50"}
    finally:
        await _close(server, session)


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, "{}", CybersecurityTunerAuthenticationError),
        (503, "{}", CybersecurityTunerConnectionError),
        (500, "{}", CybersecurityTunerConnectionError),
        (404, "{}", CybersecurityTunerResponseError),
        (200, "not json", CybersecurityTunerResponseError),
        (200, "[1, 2]", CybersecurityTunerResponseError),
    ],
)
async def test_status_errors(status: int, body: str, error: type[Exception]) -> None:
    """HTTP errors map to distinct exceptions."""

    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=status, text=body, content_type="application/json")

    server, session, client = await _client_for(handler, "/api/v1/ha/status")
    try:
        with pytest.raises(error):
            await client.get_status()
    finally:
        await _close(server, session)


async def test_events_malformed() -> None:
    """An events payload without an events list is rejected."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"last_seq": 3})

    server, session, client = await _client_for(handler, "/api/v1/ha/events")
    try:
        with pytest.raises(CybersecurityTunerResponseError):
            await client.get_events(0)
    finally:
        await _close(server, session)


async def test_timeout() -> None:
    """A slow app raises a connection error."""

    async def handler(request: web.Request) -> web.Response:
        await asyncio.sleep(1)
        return web.json_response({})

    server, session, client = await _client_for(
        handler, "/api/v1/ha/status", request_timeout=0.05
    )
    try:
        with pytest.raises(CybersecurityTunerConnectionError):
            await client.get_status()
    finally:
        await _close(server, session)


async def test_connection_refused() -> None:
    """An unreachable app raises a connection error."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({})

    server, session, client = await _client_for(handler, "/api/v1/ha/status")
    port = server.port
    await server.close()
    client = CybersecurityTunerClient("127.0.0.1", port, TOKEN, session)
    try:
        with pytest.raises(CybersecurityTunerConnectionError):
            await client.get_status()
    finally:
        await session.close()


def test_base_url() -> None:
    """IPv6 hosts are bracketed; invalid hosts raise ValueError."""
    client = CybersecurityTunerClient("fd00::1", 8099, TOKEN, None)  # type: ignore[arg-type]
    assert str(client.base_url) == "http://[fd00::1]:8099"
    with pytest.raises(ValueError):
        CybersecurityTunerClient("http://host/x", 8099, TOKEN, None)  # type: ignore[arg-type]
