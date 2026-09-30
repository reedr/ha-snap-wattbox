"""Coordinator for a WattBox."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING, UPDATE_INTERVAL
from .device import WattboxAuthError, WattboxDevice, WattboxError, WattboxInfo, WattboxState

_LOGGER = logging.getLogger(__name__)

type WattboxConfigEntry = ConfigEntry[WattboxCoordinator]


class WattboxCoordinator(DataUpdateCoordinator[WattboxState]):
    """Polls the unit and relays its pushed outlet changes."""

    config_entry: WattboxConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: WattboxConfigEntry, device: WattboxDevice
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"WattBox {device.host}",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.device = device
        device.set_push_callback(self._handle_push)

    @property
    def info(self) -> WattboxInfo:
        """The unit's identity, known once setup has succeeded."""
        assert self.device.info is not None
        return self.device.info

    async def _async_setup(self) -> None:
        """Read the unit's identity and outlet names."""
        try:
            await self.device.async_get_info()
        except WattboxAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WattboxError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_data(self) -> WattboxState:
        """Poll outlet states and meters."""
        metering = self.config_entry.options.get(CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING)
        try:
            return await self.device.async_update(metering)
        except WattboxAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WattboxError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def _handle_push(self, state: WattboxState | None) -> None:
        """Pushed outlet change, or None when the session drops."""
        if state is None:
            self.async_set_update_error(UpdateFailed(f"{self.device.host} disconnected"))
        else:
            self.async_set_updated_data(state)
