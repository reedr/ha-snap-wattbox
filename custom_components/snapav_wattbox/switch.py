"""Outlet and auto-reboot switches."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WattboxConfigEntry, WattboxCoordinator
from .entity import WattboxEntity, WattboxOutletEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a switch per outlet, plus auto reboot."""
    coord = entry.runtime_data
    entities: list[SwitchEntity] = [
        WattboxOutletSwitch(coord, i + 1) for i in range(len(coord.info.outlet_names))
    ]
    if coord.data.auto_reboot is not None:
        entities.append(WattboxAutoRebootSwitch(coord))
    async_add_entities(entities)


class WattboxOutletSwitch(WattboxOutletEntity, SwitchEntity):
    """Outlet power."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, coordinator: WattboxCoordinator, outlet: int) -> None:
        """Set up the switch."""
        super().__init__(coordinator, "outlet", outlet)
        self._attr_name = self._outlet_name

    @property
    def is_on(self) -> bool | None:
        """Whether the outlet is on."""
        outlets = self.coordinator.data.outlets_on
        return outlets[self._outlet - 1] if self._outlet <= len(outlets) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the outlet on."""
        await self._async_run(self.coordinator.device.async_set_outlet(self._outlet, "ON"))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the outlet off."""
        await self._async_run(self.coordinator.device.async_set_outlet(self._outlet, "OFF"))


class WattboxAutoRebootSwitch(WattboxEntity, SwitchEntity):
    """Whether the unit power-cycles outlets when monitored hosts stop answering."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "auto_reboot"

    def __init__(self, coordinator: WattboxCoordinator) -> None:
        """Set up the switch."""
        super().__init__(coordinator, "auto_reboot")

    @property
    def is_on(self) -> bool | None:
        """Whether auto reboot is enabled."""
        return self.coordinator.data.auto_reboot

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto reboot."""
        await self._async_run(self.coordinator.device.async_set_auto_reboot(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto reboot."""
        await self._async_run(self.coordinator.device.async_set_auto_reboot(False))
