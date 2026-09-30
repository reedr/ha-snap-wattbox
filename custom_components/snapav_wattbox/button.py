"""Outlet reset (power-cycle) buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WattboxConfigEntry, WattboxCoordinator
from .entity import WattboxOutletEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a reset button per outlet."""
    coord = entry.runtime_data
    async_add_entities(
        WattboxResetButton(coord, i + 1) for i in range(len(coord.info.outlet_names))
    )


class WattboxResetButton(WattboxOutletEntity, ButtonEntity):
    """Power-cycle an outlet, honouring its power-on delay."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: WattboxCoordinator, outlet: int) -> None:
        """Set up the button."""
        super().__init__(coordinator, "reset", outlet)
        self._attr_name = f"{self._outlet_name} Reset"

    async def async_press(self) -> None:
        """Reset the outlet."""
        await self._async_run(self.coordinator.device.async_set_outlet(self._outlet, "RESET"))
