"""Config flow for Cybersecurity Tuner."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
import voluptuous as vol

from .api import (
    CybersecurityTunerAuthenticationError,
    CybersecurityTunerClient,
    CybersecurityTunerConnectionError,
    CybersecurityTunerError,
)
from .const import (
    API_VERSION,
    CONF_EVENTS_INTERVAL,
    CONF_STATUS_INTERVAL,
    DEFAULT_EVENTS_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    MAX_INTERVAL,
    MIN_EVENTS_INTERVAL,
    MIN_STATUS_INTERVAL,
    NAME,
)

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class InvalidResponse(Exception):
    """The status payload lacks required fields."""


async def _async_validate(
    hass: HomeAssistant, host: str, port: int, token: str
) -> dict[str, Any]:
    """Call /status and return it. Raises client errors or InvalidResponse."""
    try:
        client = CybersecurityTunerClient(
            host, port, token, async_get_clientsession(hass)
        )
    except ValueError as err:
        raise CybersecurityTunerConnectionError(f"Invalid host: {err}") from err
    status = await client.get_status()
    instance_id = status.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise InvalidResponse("Status has no instance_id")
    if status.get("api_version") != API_VERSION:
        _LOGGER.warning(
            "App reports api_version %s, this integration speaks %s",
            status.get("api_version"),
            API_VERSION,
        )
    return status


def _error_key(err: Exception) -> str:
    if isinstance(err, CybersecurityTunerAuthenticationError):
        return "invalid_auth"
    if isinstance(err, CybersecurityTunerConnectionError):
        return "cannot_connect"
    if isinstance(err, (InvalidResponse, CybersecurityTunerError)):
        return "invalid_response"
    return "unknown"


class CybersecurityTunerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cybersecurity Tuner."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovery: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return CybersecurityTunerOptionsFlow()

    async def _async_try_validate(
        self, host: str, port: int, token: str, errors: dict[str, str]
    ) -> dict[str, Any] | None:
        try:
            return await _async_validate(self.hass, host, port, token)
        except (CybersecurityTunerError, InvalidResponse) as err:
            errors["base"] = _error_key(err)
        except Exception:
            _LOGGER.exception("Unexpected error validating Cybersecurity Tuner")
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup: host, port, token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_PORT: int(user_input[CONF_PORT]),
                CONF_TOKEN: user_input[CONF_TOKEN].strip(),
            }
            status = await self._async_try_validate(
                data[CONF_HOST], data[CONF_PORT], data[CONF_TOKEN], errors
            )
            if status is not None:
                await self.async_set_unique_id(status["instance_id"])
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(title=NAME, data=data)

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=65535, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_TOKEN): _PASSWORD_SELECTOR,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle Supervisor discovery: payload {host, port, token}."""
        config = discovery_info.config
        try:
            data: dict[str, Any] = {
                CONF_HOST: str(config[CONF_HOST]),
                CONF_PORT: int(config.get(CONF_PORT, DEFAULT_PORT)),
                CONF_TOKEN: str(config[CONF_TOKEN]),
            }
        except (KeyError, TypeError, ValueError):
            return self.async_abort(reason="invalid_discovery_info")

        errors: dict[str, str] = {}
        status = await self._async_try_validate(
            data[CONF_HOST], data[CONF_PORT], data[CONF_TOKEN], errors
        )
        if status is not None:
            await self.async_set_unique_id(status["instance_id"])
            # Keeps an existing entry in sync if the app's hostname/token changed.
            self._abort_if_unique_id_configured(updates=data)
        elif errors["base"] == "cannot_connect":
            # App may still be starting; validate again when the user confirms.
            self._async_abort_entries_match(
                {CONF_HOST: data[CONF_HOST], CONF_PORT: data[CONF_PORT]}
            )
        else:
            return self.async_abort(reason=errors["base"])

        self._discovery = data
        self.context["title_placeholders"] = {"name": NAME}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm Supervisor discovery."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = self._discovery
            if self.unique_id is None:
                status = await self._async_try_validate(
                    data[CONF_HOST], data[CONF_PORT], data[CONF_TOKEN], errors
                )
                if status is not None:
                    await self.async_set_unique_id(status["instance_id"])
                    self._abort_if_unique_id_configured(updates=data)
            if not errors:
                return self.async_create_entry(title=NAME, data=data)
        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"host": self._discovery[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth after the app rejected the token (401)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            status = await self._async_try_validate(
                entry.data[CONF_HOST], entry.data[CONF_PORT], token, errors
            )
            if status is not None:
                await self.async_set_unique_id(status["instance_id"])
                self._abort_if_unique_id_mismatch(reason="wrong_instance")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): _PASSWORD_SELECTOR}),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )


class CybersecurityTunerOptionsFlow(OptionsFlow):
    """Options: polling intervals."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_STATUS_INTERVAL,
                    default=options.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_STATUS_INTERVAL,
                        max=MAX_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Required(
                    CONF_EVENTS_INTERVAL,
                    default=options.get(CONF_EVENTS_INTERVAL, DEFAULT_EVENTS_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_EVENTS_INTERVAL,
                        max=MAX_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
