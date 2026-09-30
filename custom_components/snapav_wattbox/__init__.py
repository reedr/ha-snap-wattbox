"""Wattbox integration."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .coordinator import WattboxConfigEntry, WattboxCoordinator
from .device import WattboxDevice

_PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SWITCH]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: WattboxConfigEntry) -> bool:
    """Set up Wattbox device from a config entry."""

    dev = WattboxDevice(hass, entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coord = WattboxCoordinator(hass, entry, dev)
    entry.runtime_data = coord
    await coord.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: WattboxConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
