"""Support for SnapAV Wattbox outlets."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WattboxConfigEntry
from .entity import WattboxEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant,
                            config_entry: WattboxConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    """Add sensors for passed config_entry in HA."""
    coord = config_entry.runtime_data
    outlets = coord.device.outlet_names
    new_entities = [WattboxButton(coord, name=outlets[i] + " Reset", index=i+1) for i in range(len(outlets))]
    if new_entities:
        async_add_entities(new_entities)

DESC = ButtonEntityDescription(
    key="outlet",
    translation_key="outlet",
    device_class=ButtonDeviceClass.RESTART
)


class WattboxButton(ButtonEntity, WattboxEntity):
    """Port state sensor."""

    def __init__(self, coord, name: str, index: int) -> None:
        """Set the class."""
        super().__init__(coord, DESC, name)
        self._index = index

    @property
    def entity_type(self) -> str:
        """Type of entity."""
        return "Button"

    async def async_press(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self.coordinator.device.async_reset(self._index)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.device is not None:
            self._state = self.coordinator.device.is_on(self._index-1)
            self.async_write_ha_state()
