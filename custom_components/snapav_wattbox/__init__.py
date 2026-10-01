"""The SnapAV WattBox integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import WattboxConfigEntry, WattboxCoordinator
from .device import WattboxDevice
from .migration import async_migrate_legacy_entry, async_migrate_unique_ids

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the rename_outlet action on outlet switches."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "rename_outlet",
        entity_domain=SWITCH_DOMAIN,
        entity_device_classes=[SwitchDeviceClass.OUTLET],
        schema={vol.Required(CONF_NAME): cv.string},
        func="async_rename_outlet",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WattboxConfigEntry) -> bool:
    """Set up a WattBox from a config entry."""
    await async_migrate_legacy_entry(hass, entry)

    dev = WattboxDevice(
        hass, entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    coord = WattboxCoordinator(hass, entry, dev)
    entry.runtime_data = coord
    entry.async_on_unload(dev.async_close)

    async def _async_stop(_event: Event) -> None:
        await dev.async_close()

    # Entries aren't unloaded at shutdown; log out so the unit frees the session.
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop))
    await coord.async_config_entry_first_refresh()

    async_migrate_unique_ids(hass, entry, coord.info)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass: HomeAssistant, entry: WattboxConfigEntry) -> None:
    """Reload to add or remove the per-outlet meters."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: WattboxConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
