"""Config, reauth, reconfigure and options flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.snapav_wattbox.const import CONF_OUTLET_METERING, DOMAIN

from .conftest import DATA, HOST, TAG


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_user_flow(hass: HomeAssistant, wattbox) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DATA, "host": f" {HOST} "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "AV-Rack-1"
    assert result["data"] == DATA
    assert result["result"].unique_id == TAG
    await hass.async_block_till_done()


async def test_user_flow_errors(hass: HomeAssistant, wattbox) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**DATA, "password": "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    await wattbox.stop()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(hass: HomeAssistant, wattbox) -> None:
    """The same unit at a new address updates the existing entry."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=TAG, data={**DATA, "host": "10.0.0.9"})
    entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == HOST


async def test_reauth(hass: HomeAssistant, wattbox) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=TAG, data={**DATA, "password": "old"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "wattbox", "password": "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "wattbox", "password": "pass"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["password"] == "pass"


async def test_reconfigure(hass: HomeAssistant, wattbox) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=TAG, data={**DATA, "host": "10.0.0.9"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["host"] == HOST


async def test_reconfigure_other_unit(hass: HomeAssistant, wattbox) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="ST_OTHER", data=DATA)
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["reason"] == "wrong_device"


async def test_options(hass: HomeAssistant, wattbox) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=TAG, data=DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.av_rack_1_amp_power") is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_OUTLET_METERING: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_OUTLET_METERING: False}
