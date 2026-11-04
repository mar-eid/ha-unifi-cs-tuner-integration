"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_HASSIO, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cybersecurity_tuner.api import (
    CybersecurityTunerAuthenticationError,
    CybersecurityTunerConnectionError,
)
from custom_components.cybersecurity_tuner.const import (
    CONF_EVENTS_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
)

from .conftest import ENTRY_DATA, INSTANCE_ID

USER_INPUT = {CONF_HOST: " 192.168.1.10 ", CONF_PORT: 8099, CONF_TOKEN: "secret-token"}
DISCOVERY = HassioServiceInfo(
    config={"host": "local-cybersecurity-tuner", "port": 8099, "token": "disc-token"},
    name="Cybersecurity Tuner",
    slug="local_cybersecurity_tuner",
    uuid="1234",
)


@pytest.fixture(autouse=True)
def no_setup() -> None:
    """Don't actually set up the entry after the flow."""
    with patch(
        "custom_components.cybersecurity_tuner.async_setup_entry", return_value=True
    ):
        yield


async def test_user_flow(hass: HomeAssistant, mock_client) -> None:
    """A valid host/port/token creates an entry keyed on instance_id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cybersecurity Tuner"
    assert result["data"] == {
        CONF_HOST: "192.168.1.10",
        CONF_PORT: 8099,
        CONF_TOKEN: "secret-token",
    }
    assert result["result"].unique_id == INSTANCE_ID


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (CybersecurityTunerAuthenticationError, "invalid_auth"),
        (CybersecurityTunerConnectionError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_client, side_effect: type[Exception], error: str
) -> None:
    """Errors are shown, and the flow recovers."""
    get_status, _ = mock_client
    status = get_status.return_value
    get_status.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    get_status.side_effect = None
    get_status.return_value = status
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_missing_instance_id(hass: HomeAssistant, mock_client) -> None:
    """A payload without instance_id is not a Cybersecurity Tuner."""
    mock_client[0].return_value = {"healthy": True}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["errors"] == {"base": "invalid_response"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """The same instance cannot be added twice; host/token are updated."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.168.1.10"


async def test_hassio_discovery(hass: HomeAssistant, mock_client) -> None:
    """Supervisor discovery shows a confirm step and creates the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: "local-cybersecurity-tuner",
        CONF_PORT: 8099,
        CONF_TOKEN: "disc-token",
    }
    assert result["result"].unique_id == INSTANCE_ID


async def test_hassio_discovery_app_starting(hass: HomeAssistant, mock_client) -> None:
    """If the app is still starting, validation happens on confirm."""
    get_status, _ = mock_client
    status = get_status.return_value
    get_status.side_effect = CybersecurityTunerConnectionError
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["step_id"] == "hassio_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "cannot_connect"}

    get_status.side_effect = None
    get_status.return_value = status
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == INSTANCE_ID


async def test_hassio_discovery_updates_existing(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """Discovery of a configured instance updates its token and aborts."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_TOKEN] == "disc-token"


async def test_hassio_discovery_bad_token(hass: HomeAssistant, mock_client) -> None:
    """A discovery payload with a rejected token aborts."""
    mock_client[0].side_effect = CybersecurityTunerAuthenticationError
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


async def test_reauth(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """Reauth stores the new token."""
    config_entry.add_to_hass(hass)
    get_status, _ = mock_client
    status = get_status.return_value
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    get_status.side_effect = CybersecurityTunerAuthenticationError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    get_status.side_effect = None
    get_status.return_value = status
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "new-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {**ENTRY_DATA, CONF_TOKEN: "new-token"}


async def test_reauth_wrong_instance(
    hass: HomeAssistant, mock_client, config_entry: MockConfigEntry
) -> None:
    """Reauth against another installation is refused."""
    config_entry.add_to_hass(hass)
    mock_client[0].return_value = {"instance_id": "other"}
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "new-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_instance"


async def test_options_flow(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Scan intervals can be changed."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_STATUS_INTERVAL: 60.0, CONF_EVENTS_INTERVAL: 15.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_STATUS_INTERVAL: 60, CONF_EVENTS_INTERVAL: 15}
