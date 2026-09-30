"""Base entity for WattBox."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import WattboxCoordinator
from .device import WattboxError


class WattboxEntity(CoordinatorEntity[WattboxCoordinator]):
    """An entity of one WattBox; unique IDs are ``<service tag>_<key>``."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WattboxCoordinator, key: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        info = coordinator.info
        self._attr_unique_id = f"{info.service_tag}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.service_tag)},
            manufacturer=MANUFACTURER,
            model=info.model,
            name=info.hostname,
            sw_version=info.firmware,
            serial_number=info.service_tag,
            configuration_url=f"http://{coordinator.device.host}",
        )

    async def _async_run(self, command: Awaitable[None]) -> None:
        """Run a device command, reporting failures to the caller."""
        try:
            await command
        except WattboxError as err:
            raise HomeAssistantError(f"WattBox {self.coordinator.device.host}: {err}") from err


class WattboxOutletEntity(WattboxEntity):
    """An entity tied to one outlet (1-based), named after it."""

    def __init__(self, coordinator: WattboxCoordinator, key: str, outlet: int) -> None:
        """Set up the entity."""
        super().__init__(coordinator, f"{key}_{outlet}")
        self._outlet = outlet
        self._outlet_name = coordinator.info.outlet_names[outlet - 1]
