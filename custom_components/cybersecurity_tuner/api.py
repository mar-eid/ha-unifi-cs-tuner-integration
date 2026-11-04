"""Async client for the Cybersecurity Tuner app's Home Assistant API (v1).

This module deliberately has no Home Assistant imports so it can be unit
tested on its own. Callers pass in an ``aiohttp.ClientSession`` (in HA:
``homeassistant.helpers.aiohttp_client.async_get_clientsession``).
"""

from __future__ import annotations

from typing import Any

import aiohttp
from yarl import URL

from .const import EVENTS_LIMIT, EVENTS_PATH, REQUEST_TIMEOUT, STATUS_PATH


class CybersecurityTunerError(Exception):
    """Base error for the Cybersecurity Tuner client."""


class CybersecurityTunerConnectionError(CybersecurityTunerError):
    """The app could not be reached, timed out, or is starting up (503)."""


class CybersecurityTunerAuthenticationError(CybersecurityTunerError):
    """The app rejected the token (401)."""


class CybersecurityTunerResponseError(CybersecurityTunerError):
    """The app answered with an unexpected status code or payload."""


class CybersecurityTunerClient:
    """Minimal client for ``/api/v1/ha/*``."""

    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        session: aiohttp.ClientSession,
        *,
        request_timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the client.

        Raises ``ValueError`` if ``host``/``port`` cannot form a valid URL.
        """
        self._base_url = URL.build(scheme="http", host=host.strip(), port=int(port))
        self._token = token
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

    @property
    def base_url(self) -> URL:
        """Return the base URL of the app."""
        return self._base_url

    async def get_status(self) -> dict[str, Any]:
        """Return the ``/status`` payload."""
        data = await self._request(STATUS_PATH)
        if not isinstance(data, dict):
            raise CybersecurityTunerResponseError("Status payload is not an object")
        return data

    async def get_events(self, after: int, limit: int = EVENTS_LIMIT) -> dict[str, Any]:
        """Return events with ``seq > after`` (oldest first, at most ``limit``)."""
        data = await self._request(
            EVENTS_PATH, params={"after": str(int(after)), "limit": str(int(limit))}
        )
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise CybersecurityTunerResponseError("Events payload is malformed")
        return data

    async def _request(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self._base_url.with_path(path)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with self._session.get(
                url, headers=headers, params=params, timeout=self._timeout
            ) as resp:
                if resp.status == 401:
                    raise CybersecurityTunerAuthenticationError(
                        "Invalid or missing API token"
                    )
                if resp.status == 503:
                    raise CybersecurityTunerConnectionError("App is starting up")
                if resp.status >= 500:
                    raise CybersecurityTunerConnectionError(
                        f"App returned HTTP {resp.status}"
                    )
                if resp.status != 200:
                    raise CybersecurityTunerResponseError(
                        f"Unexpected HTTP {resp.status} from {path}"
                    )
                try:
                    return await resp.json(content_type=None)
                except ValueError as err:
                    raise CybersecurityTunerResponseError(
                        f"Invalid JSON from {path}"
                    ) from err
        except TimeoutError as err:
            raise CybersecurityTunerConnectionError(
                f"Timeout talking to {self._base_url}"
            ) from err
        except aiohttp.ClientError as err:
            raise CybersecurityTunerConnectionError(
                f"Error talking to {self._base_url}: {err}"
            ) from err
