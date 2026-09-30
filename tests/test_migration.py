"""Import of the legacy "Wattbox" package's config entries."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.snapav_wattbox.const import CONF_LEGACY_ENTRY, DOMAIN, LEGACY_DOMAIN

from .fake_wattbox import FakeWattbox

RACK = {"host": "10.0.1.51", "username": "wattbox", "password": "pass"}
GYM = {"host": "10.0.1.52", "username": "wattbox", "password": "pass"}
RACK_TAG = "ST000000000001"
GYM_TAG = "ST000000000002"
_real_open = asyncio.open_connection


@pytest.fixture
async def units(socket_enabled):
    """Two fake units, reached by their "LAN" addresses."""
    rack = FakeWattbox(names=["Araknis SW24", "Fan Power", "Outlet 3"], service_tag=RACK_TAG)
    # Gym still has the factory hostname.
    gym = FakeWattbox(names=["Gym TV", "Gym Amp"], hostname="WattBox", service_tag=GYM_TAG)
    await rack.start()
    await gym.start()
    ports = {RACK["host"]: rack.port, GYM["host"]: gym.port}

    async def open_connection(host, port, **kwargs):
        return await _real_open("127.0.0.1", ports[host], **kwargs)

    with patch(
        "custom_components.snapav_wattbox.device.asyncio.open_connection", open_connection
    ):
        yield rack, gym
    await rack.stop()
    await gym.stop()


def _legacy(hass: HomeAssistant, title: str, data: dict, hostname: str, outlets: dict) -> tuple:
    """Registry contents left behind by the old package."""
    entry = MockConfigEntry(domain=LEGACY_DOMAIN, title=title, data=data)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(LEGACY_DOMAIN, hostname)},
        manufacturer="SnapAV",
        name=hostname,
    )
    ent_reg = er.async_get(hass)
    for name, object_id in outlets.items():
        for domain, suffix in (("switch", ""), ("button", " Reset")):
            ent_reg.async_get_or_create(
                domain,
                LEGACY_DOMAIN,
                f"{hostname}_{name}{suffix}",
                config_entry=entry,
                device_id=device.id,
                suggested_object_id=f"{object_id}{'_reset' if suffix else ''}",
            )
    return entry, device.id


def _setup_legacy(hass: HomeAssistant) -> tuple:
    rack = _legacy(
        hass,
        "AV Rack 1",
        RACK,
        "AV-Rack-1",
        {"Araknis SW24": "av_rack_1_araknis_sw24", "Fan Power": "av_rack_1_fan_power",
         "Renamed Since": "av_rack_1_renamed_since"},
    )
    gym = _legacy(
        hass, "Gym", GYM, "WattBox", {"Gym TV": "wattbox_gym_tv", "Gym Amp": "wattbox_gym_amp"}
    )
    area = ar.async_get(hass).async_create("Lower Level Gym")
    dr.async_get(hass).async_update_device(gym[1], area_id=area.id, name_by_user="Gym")
    er.async_get(hass).async_update_entity("switch.wattbox_gym_amp", labels={"av"})
    return rack, gym


async def test_import_all(hass: HomeAssistant, units) -> None:
    """One import brings over every legacy unit with its IDs."""
    (_rack_legacy, rack_dev), (_gym_legacy, gym_dev) = _setup_legacy(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["import_legacy", "manual"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_legacy"}
    )
    assert result["description_placeholders"] == {"count": "2", "titles": "AV Rack 1, Gym"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entries = {e.title: e for e in hass.config_entries.async_entries(DOMAIN)}
    assert set(entries) == {"AV Rack 1", "Gym"}
    assert hass.config_entries.async_entries(LEGACY_DOMAIN) == []
    for entry in entries.values():
        assert CONF_LEGACY_ENTRY not in entry.data
    assert entries["AV Rack 1"].unique_id == RACK_TAG
    assert entries["Gym"].unique_id == GYM_TAG

    ent_reg = er.async_get(hass)
    expected = {
        "switch.av_rack_1_araknis_sw24": f"{RACK_TAG}_outlet_1",
        "button.av_rack_1_araknis_sw24_reset": f"{RACK_TAG}_reset_1",
        "switch.av_rack_1_fan_power": f"{RACK_TAG}_outlet_2",
        "switch.wattbox_gym_tv": f"{GYM_TAG}_outlet_1",
        "switch.wattbox_gym_amp": f"{GYM_TAG}_outlet_2",
        "button.wattbox_gym_amp_reset": f"{GYM_TAG}_reset_2",
    }
    for entity_id, unique_id in expected.items():
        reg = ent_reg.async_get(entity_id)
        assert reg.unique_id == unique_id, entity_id
        assert reg.platform == DOMAIN
        if entity_id.startswith("switch."):
            assert hass.states.get(entity_id).state == "on", entity_id
    assert ent_reg.async_get("switch.wattbox_gym_amp").labels == {"av"}
    assert ent_reg.async_get("switch.wattbox_gym_amp").device_id == gym_dev

    # The outlet renamed on the unit can't be matched; it stays behind, unavailable.
    stale = ent_reg.async_get("switch.av_rack_1_renamed_since")
    assert stale.unique_id == "AV-Rack-1_Renamed Since"
    # Outlet 3 had no legacy entity and is new.
    assert ent_reg.async_get_entity_id("switch", DOMAIN, f"{RACK_TAG}_outlet_3")

    dev_reg = dr.async_get(hass)
    gym = dev_reg.async_get(gym_dev)
    assert gym.identifiers == {(DOMAIN, GYM_TAG)}
    assert gym.name_by_user == "Gym" and gym.area_id == "lower_level_gym"
    assert gym.serial_number == GYM_TAG
    assert dev_reg.async_get(rack_dev).identifiers == {(DOMAIN, RACK_TAG)}
    # No duplicate devices were created.
    assert len(dr.async_entries_for_config_entry(dev_reg, entries["Gym"].entry_id)) == 1


async def test_manual_path(hass: HomeAssistant, units) -> None:
    _setup_legacy(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_no_legacy_shows_form(hass: HomeAssistant, units) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM


async def test_takeover_when_unreachable(hass: HomeAssistant, units) -> None:
    """If the unit is offline, the takeover still happens; rekeying waits for it."""
    (_, _), (gym_legacy, gym_dev) = _setup_legacy(hass)
    _rack, gym = units
    await gym.stop()
    entry = MockConfigEntry(
        domain=DOMAIN, title="Gym", data={**GYM, CONF_LEGACY_ENTRY: gym_legacy.entry_id}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    reg = ent_reg.async_get("switch.wattbox_gym_amp")
    assert reg.platform == DOMAIN and reg.config_entry_id == entry.entry_id
    assert reg.unique_id == "WattBox_Gym Amp"
    assert hass.config_entries.async_get_entry(gym_legacy.entry_id) is None
    assert dr.async_get(hass).async_get(gym_dev).identifiers == {(DOMAIN, "WattBox")}
