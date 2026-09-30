"""Supply voltage and UPS binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WattboxConfigEntry, WattboxCoordinator
from .device import WattboxState
from .entity import WattboxEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WattboxBinarySensorDescription(BinarySensorEntityDescription):
    """A whole-unit binary sensor."""

    value_fn: Callable[[WattboxState], bool | None]


# SAFETY and PROBLEM are "on" when something is wrong.
SAFE_VOLTAGE = WattboxBinarySensorDescription(
    key="safe_voltage",
    translation_key="safe_voltage",
    device_class=BinarySensorDeviceClass.SAFETY,
    value_fn=lambda s: s.power.voltage_fault if s.power else None,
)

UPS_BINARY_SENSORS = (
    WattboxBinarySensorDescription(
        key="ups_power",
        translation_key="ups_power",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda s: not s.ups.power_lost if s.ups else None,
    ),
    WattboxBinarySensorDescription(
        key="battery_health",
        translation_key="battery_health",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: not s.ups.battery_healthy if s.ups else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the voltage-safety sensor, and UPS sensors if one is attached."""
    coord = entry.runtime_data
    descs: list[WattboxBinarySensorDescription] = []
    if coord.data.power is not None:
        descs.append(SAFE_VOLTAGE)
    if coord.info.has_ups:
        descs += UPS_BINARY_SENSORS
    async_add_entities(WattboxBinarySensor(coord, desc) for desc in descs)


class WattboxBinarySensor(WattboxEntity, BinarySensorEntity):
    """A whole-unit binary sensor."""

    entity_description: WattboxBinarySensorDescription

    def __init__(
        self, coordinator: WattboxCoordinator, desc: WattboxBinarySensorDescription
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def is_on(self) -> bool | None:
        """The state."""
        return self.entity_description.value_fn(self.coordinator.data)
