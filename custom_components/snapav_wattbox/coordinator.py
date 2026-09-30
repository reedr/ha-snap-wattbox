"""Coordinator."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .device import WattboxDevice

_LOGGER = logging.getLogger(__name__)

type WattboxConfigEntry = ConfigEntry[WattboxCoordinator]

class WattboxCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: WattboxConfigEntry,
        device: WattboxDevice,
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Wattbox Coordinator",
            config_entry=config_entry,
            setup_method=self.async_init,
            update_method=self.async_update,
            update_interval=timedelta(seconds=5),
            always_update=False,
        )
        self._device = device

    @property
    def device(self) -> WattboxDevice:
        """The device handle."""
        return self._device

    async def async_init(self):
        """Init the device."""
        await self.device.async_init(self.update_callback)

    async def async_update(self):
        """For polling."""
        await self.device.update_data()

    @callback
    def update_callback(self, data):
        """Incoming data callback."""
        self.hass.add_job(self.async_set_updated_data, data)
