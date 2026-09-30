"""Wattbox Entity Base class."""

import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WATTBOX_MANUFACTURER
from .coordinator import WattboxCoordinator
from .device import DEVICE_MODEL, WattboxDevice

_LOGGER = logging.getLogger(__name__)


class WattboxEntity(CoordinatorEntity[WattboxCoordinator]):
    """Base class."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WattboxCoordinator, desc: EntityDescription, name: str
    ) -> None:
        """Set up entity."""
        super().__init__(coordinator, desc)

        self.entity_description = desc
        self._state = None
        self._attr_name = name
        self._attr_unique_id = f"{self.coordinator.device.device_id}_{name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device.device_id)},
            manufacturer=WATTBOX_MANUFACTURER,
            model=self.coordinator.device.get_data_value(DEVICE_MODEL),
            name=coordinator.device.device_id,
        )

    #        _LOGGER.error(f"new entity={entity} name={self._attr_name} unique_id={self.unique_id}")

    @property
    def entity_type(self) -> str | None:
        """Type of entity."""
        return None

    @property
    def device_id(self):
        """Return entity id."""
        return self.entity_description.key

    @property
    def available(self) -> bool:
        """Return online state."""
        return self.coordinator.device.online

    @property
    def device(self) -> WattboxDevice:
        """Return device."""
        return self.coordinator.device

    @property
    def state(self):
        """Return state."""
        return self._state
