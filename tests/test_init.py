"""Setup, entities and runtime behaviour."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotSupported, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.snapav_wattbox.const import CONF_OUTLET_METERING, DOMAIN

from .conftest import DATA, TAG


async def _setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="AV-Rack-1", unique_id=TAG, data=DATA, options=options
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities(hass: HomeAssistant, wattbox) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, TAG), entry.entry_id)
    assert device.name == "AV-Rack-1"
    assert device.model == "WB-800-IPVM-6"
    assert device.serial_number == TAG
    assert device.sw_version == "2.8.0.0"

    assert hass.states.get("switch.av_rack_1_amp").state == STATE_ON
    assert hass.states.get("button.av_rack_1_amp_reset") is not None
    assert hass.states.get("switch.av_rack_1_auto_reboot").state == STATE_OFF
    assert hass.states.get("sensor.av_rack_1_power").state == "180.0"
    assert hass.states.get("sensor.av_rack_1_voltage").state == "120.1"
    assert hass.states.get("sensor.av_rack_1_current").state == "1.5"
    assert hass.states.get("sensor.av_rack_1_amp_power").state == "20.0"
    assert hass.states.get("binary_sensor.av_rack_1_supply_voltage").state == STATE_OFF

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("switch.av_rack_1_amp").unique_id == f"{TAG}_outlet_2"
    assert ent_reg.async_get("button.av_rack_1_amp_reset").unique_id == f"{TAG}_reset_2"
    # Per-outlet current is there but disabled; no UPS entities without a UPS.
    assert ent_reg.async_get("sensor.av_rack_1_amp_current").disabled_by is not None
    assert not [e for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
                if "ups" in e.entity_id]

    await hass.config_entries.async_unload(entry.entry_id)
    await asyncio.sleep(0.05)
    assert wattbox.open_clients == 0


async def test_controls(hass: HomeAssistant, wattbox) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.av_rack_1_amp"}, blocking=True
    )
    assert wattbox.outlets[1] is False
    assert hass.states.get("switch.av_rack_1_amp").state == STATE_OFF

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.av_rack_1_tv_reset"}, blocking=True
    )
    assert "!OutletSet=3,RESET" in wattbox.commands

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.av_rack_1_auto_reboot"}, blocking=True
    )
    assert wattbox.auto_reboot
    assert hass.states.get("switch.av_rack_1_auto_reboot").state == STATE_ON


async def test_push_and_reconnect(hass: HomeAssistant, wattbox) -> None:
    await _setup(hass)
    wattbox.set_outlet(4, False)
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    assert hass.states.get("switch.av_rack_1_roku").state == STATE_OFF

    wattbox.disconnect_all()
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    assert hass.states.get("switch.av_rack_1_roku").state == STATE_UNAVAILABLE

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert hass.states.get("switch.av_rack_1_roku").state == STATE_OFF
    assert wattbox.logins == 2


async def test_metering_off(hass: HomeAssistant, wattbox) -> None:
    await _setup(hass, **{CONF_OUTLET_METERING: False})
    assert hass.states.get("sensor.av_rack_1_power") is not None
    assert hass.states.get("sensor.av_rack_1_amp_power") is None
    assert not any("OutletPowerStatus" in c for c in wattbox.commands)


async def test_ups_entities(hass: HomeAssistant, wattbox) -> None:
    wattbox.ups = "80,20,Good,True,12,True,False"
    await _setup(hass)
    assert hass.states.get("sensor.av_rack_1_battery").state == "80"
    assert hass.states.get("sensor.av_rack_1_ups_runtime").state == "12"
    assert hass.states.get("binary_sensor.av_rack_1_ups_utility_power").state == STATE_OFF
    assert hass.states.get("binary_sensor.av_rack_1_ups_battery").state == STATE_OFF


async def test_not_ready(hass: HomeAssistant, wattbox) -> None:
    await wattbox.stop()
    entry = MockConfigEntry(domain=DOMAIN, title="AV-Rack-1", unique_id=TAG, data=DATA)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_bad_login_starts_reauth(hass: HomeAssistant, wattbox) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="AV-Rack-1", unique_id=TAG, data={**DATA, "password": "nope"}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_rename_outlet(hass: HomeAssistant, wattbox) -> None:
    """Renaming changes the unit's name and the entities' names, not their IDs."""
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "rename_outlet",
        {"entity_id": "switch.av_rack_1_amp", "name": " Rack Amp "},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert wattbox.names[1] == "Rack Amp"
    assert wattbox.names[0] == "Switch"
    assert "!OutletNameSetAll={Switch},{Rack Amp},{TV},{Roku},{Port},{Savant}" in wattbox.commands
    amp = hass.states.get("switch.av_rack_1_amp")
    assert amp.attributes["friendly_name"] == "AV-Rack-1 Rack Amp"
    assert (
        hass.states.get("button.av_rack_1_amp_reset").attributes["friendly_name"]
        == "AV-Rack-1 Rack Amp Reset"
    )
    assert (
        hass.states.get("sensor.av_rack_1_amp_power").attributes["friendly_name"]
        == "AV-Rack-1 Rack Amp Power"
    )


@pytest.mark.parametrize("name", ["", "x" * 32, "A{B}", "A,B", "Café"])
async def test_rename_outlet_rejects(hass: HomeAssistant, wattbox, name: str) -> None:
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "rename_outlet",
            {"entity_id": "switch.av_rack_1_amp", "name": name},
            blocking=True,
        )
    assert not any(c.startswith("!OutletNameSetAll") for c in wattbox.commands)


async def test_rename_skips_auto_reboot(hass: HomeAssistant, wattbox) -> None:
    """The action only applies to outlet switches."""
    await _setup(hass)
    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            DOMAIN,
            "rename_outlet",
            {"entity_id": "switch.av_rack_1_auto_reboot", "name": "Nope"},
            blocking=True,
        )
    assert not any(c.startswith("!OutletNameSetAll") for c in wattbox.commands)
