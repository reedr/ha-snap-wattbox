"""The SnapAV WattBox integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .coordinator import WattboxConfigEntry, WattboxCoordinator
from .device import WattboxDevice
from .migration import async_migrate_legacy_entry, async_migrate_unique_ids

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: WattboxConfigEntry) -> bool:
    """Set up a WattBox from a config entry."""
    await async_migrate_legacy_entry(hass, entry)

    dev = WattboxDevice(
        hass, entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    coord = WattboxCoordinator(hass, entry, dev)
    entry.runtime_data = coord
    entry.async_on_unload(dev.async_close)
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
