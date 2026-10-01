"""The telnet client against the fake WattBox."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.core import HomeAssistant

from custom_components.snapav_wattbox.device import (
    OutletPower,
    WattboxAuthError,
    WattboxCommandError,
    WattboxConnectionError,
    WattboxDevice,
    parse_outlet_names,
    parse_outlet_power,
    parse_power_status,
    parse_ups_status,
)

from .conftest import HOST, TAG


def test_parsers() -> None:
    assert parse_outlet_names("{A},{B C},{}", 4) == ["A", "B C", "Outlet 3", "Outlet 4"]
    assert parse_outlet_names("{A},{B},{C}", 2) == ["A", "B"]
    assert parse_outlet_power("3,1.01,0.02,116.50") == (3, OutletPower(1.01, 0.02, 116.5))
    status = parse_power_status("60.00,600.00,110.00,0")
    assert (status.amps, status.watts, status.volts, status.voltage_fault) == (60, 600, 110, False)
    assert parse_power_status("0.01,22.31,90.00,1").voltage_fault
    ups = parse_ups_status("50,0,Good,False,25,True,False")
    assert ups.battery_charge == 50 and ups.battery_healthy and not ups.power_lost
    assert ups.runtime == 25 and ups.alarm_enabled and not ups.alarm_muted
    with pytest.raises(ValueError):
        parse_power_status("1,2")


async def test_info_and_update(hass: HomeAssistant, wattbox) -> None:
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    info = await dev.async_get_info()
    assert info.service_tag == TAG
    assert info.hostname == "AV-Rack-1"
    assert info.model == "WB-800-IPVM-6"
    assert info.firmware == "2.8.0.0"
    assert info.outlet_names == wattbox.names
    assert not info.has_ups

    wattbox.outlets[1] = False
    state = await dev.async_update(outlet_metering=True)
    assert state.outlets_on == (True, False, True, True, True, True)
    assert state.power.watts == 180 and not state.power.voltage_fault
    assert state.outlet_power[1].watts == 10 and state.outlet_power[2].watts == 0
    assert state.auto_reboot is False
    assert state.ups is None
    assert wattbox.logins == 1
    await dev.async_close()
    await asyncio.sleep(0.05)
    assert wattbox.commands[-1] == "!Exit"
    assert wattbox.open_clients == 0


async def test_no_metering_on_unmetered_models(hass: HomeAssistant, wattbox) -> None:
    """WB-150/250 have no meter: power is never asked for."""
    wattbox.model = "WB-250-IPW-2"
    wattbox.metering = False
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    state = await dev.async_update(outlet_metering=True)
    assert not dev.metered
    assert state.power is None and state.outlet_power == {}
    assert not any("Power" in c for c in wattbox.commands)
    await dev.async_close()


async def test_metering_survives_a_transient_error(hass: HomeAssistant, wattbox) -> None:
    """One #Error on a metered unit doesn't turn metering off."""
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    wattbox.metering = False
    state = await dev.async_update(outlet_metering=True)
    assert dev.metered and state.power is None
    wattbox.metering = True
    state = await dev.async_update(outlet_metering=True)
    assert state.power is not None and state.outlet_power
    await dev.async_close()


async def test_closed_client_does_not_reconnect(hass: HomeAssistant, wattbox) -> None:
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    await dev.async_update(outlet_metering=False)
    await dev.async_close()
    with pytest.raises(WattboxConnectionError):
        await dev.async_update(outlet_metering=False)
    assert wattbox.logins == 1


async def test_rename_keeps_other_names_raw(hass: HomeAssistant, wattbox) -> None:
    """Unnamed outlets are sent back as the unit had them, not as 'Outlet N'."""
    wattbox.names[2] = ""
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    await dev.async_get_info()
    await dev.async_set_outlet_name(1, "Rack")
    sent = next(c for c in wattbox.commands if c.startswith("!OutletNameSetAll"))
    assert sent == "!OutletNameSetAll={Rack},{Amp},{},{Roku},{Port},{Savant}"
    await dev.async_close()


async def test_ups(hass: HomeAssistant, wattbox) -> None:
    wattbox.ups = "80,20,Bad,True,12,True,False"
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    assert (await dev.async_get_info()).has_ups
    state = await dev.async_update(outlet_metering=False)
    assert state.ups.battery_charge == 80 and not state.ups.battery_healthy
    assert state.ups.power_lost
    await dev.async_close()


async def test_bad_password(hass: HomeAssistant, wattbox) -> None:
    dev = WattboxDevice(hass, HOST, "wattbox", "wrong")
    with pytest.raises(WattboxAuthError):
        await dev.async_get_info()
    assert not dev.connected


async def test_cannot_connect(hass: HomeAssistant, wattbox) -> None:
    await wattbox.stop()
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    with pytest.raises(WattboxConnectionError):
        await dev.async_get_info()


async def test_commands_and_push(hass: HomeAssistant, wattbox) -> None:
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    pushed = []
    dev.set_push_callback(pushed.append)
    await dev.async_update(outlet_metering=False)

    await dev.async_set_outlet(2, "OFF")
    assert wattbox.outlets[1] is False
    assert dev.state.outlets_on[1] is False
    assert "!OutletSet=2,OFF" in wattbox.commands

    await dev.async_set_outlet(2, "RESET")
    assert "!OutletSet=2,RESET" in wattbox.commands

    with pytest.raises(WattboxCommandError):
        await dev.async_set_outlet(9, "ON")

    await dev.async_set_auto_reboot(True)
    assert wattbox.auto_reboot and dev.state.auto_reboot

    pushed.clear()
    wattbox.set_outlet(3, False)
    await asyncio.sleep(0.05)
    assert pushed and pushed[-1].outlets_on[2] is False
    # Other state survives a push.
    assert pushed[-1].auto_reboot is True
    await dev.async_close()


async def test_disconnect_and_reconnect(hass: HomeAssistant, wattbox) -> None:
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    pushed = []
    dev.set_push_callback(pushed.append)
    await dev.async_update(outlet_metering=False)

    wattbox.disconnect_all()
    await asyncio.sleep(0.05)
    assert pushed[-1] is None
    assert not dev.connected

    await dev.async_update(outlet_metering=False)
    assert dev.connected and wattbox.logins == 2
    await dev.async_close()


async def test_silent_unit_times_out(hass: HomeAssistant, wattbox) -> None:
    """A unit that stops answering is dropped; the next request logs in again."""
    dev = WattboxDevice(hass, HOST, "wattbox", "pass")
    await dev.async_update(outlet_metering=False)
    wattbox.silent = True
    with pytest.raises(WattboxConnectionError):
        await dev.async_update(outlet_metering=False)
    assert not dev.connected
    wattbox.silent = False
    await dev.async_update(outlet_metering=False)
    assert wattbox.logins == 2
    await dev.async_close()
