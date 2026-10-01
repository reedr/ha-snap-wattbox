"""Power meter and UPS sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING
from .coordinator import WattboxConfigEntry, WattboxCoordinator
from .device import OutletPower, WattboxState
from .entity import WattboxEntity, WattboxOutletEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class WattboxSensorDescription(SensorEntityDescription):
    """A whole-unit sensor."""

    value_fn: Callable[[WattboxState], float | int | None]


@dataclass(frozen=True, kw_only=True)
class OutletSensorDescription(SensorEntityDescription):
    """A per-outlet meter sensor; ``name_suffix`` follows the outlet's name."""

    name_suffix: str
    value_fn: Callable[[OutletPower], float]


POWER_SENSORS = (
    WattboxSensorDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.power.watts if s.power else None,
    ),
    WattboxSensorDescription(
        key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.power.amps if s.power else None,
    ),
    WattboxSensorDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.power.volts if s.power else None,
    ),
)

UPS_SENSORS = (
    WattboxSensorDescription(
        key="battery_charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.ups.battery_charge if s.ups else None,
    ),
    WattboxSensorDescription(
        key="battery_load",
        translation_key="battery_load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.ups.battery_load if s.ups else None,
    ),
    WattboxSensorDescription(
        key="battery_runtime",
        translation_key="battery_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.ups.runtime if s.ups else None,
    ),
)

OUTLET_SENSORS = (
    OutletSensorDescription(
        key="power",
        name_suffix="Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: p.watts,
    ),
    OutletSensorDescription(
        key="current",
        name_suffix="Current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda p: p.amps,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add meter sensors the unit supports, and UPS sensors if one is attached."""
    coord = entry.runtime_data
    entities: list[SensorEntity] = []
    if coord.device.metered:
        entities += [WattboxSensor(coord, desc) for desc in POWER_SENSORS]
    if coord.info.has_ups:
        entities += [WattboxSensor(coord, desc) for desc in UPS_SENSORS]
    if coord.device.metered and entry.options.get(CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING):
        entities += [
            WattboxOutletSensor(coord, desc, outlet)
            for outlet in range(1, len(coord.info.outlet_names) + 1)
            for desc in OUTLET_SENSORS
        ]
    async_add_entities(entities)


class WattboxSensor(WattboxEntity, SensorEntity):
    """A whole-unit reading."""

    entity_description: WattboxSensorDescription

    def __init__(self, coordinator: WattboxCoordinator, desc: WattboxSensorDescription) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> float | int | None:
        """The reading."""
        return self.entity_description.value_fn(self.coordinator.data)


class WattboxOutletSensor(WattboxOutletEntity, SensorEntity):
    """One outlet's reading."""

    entity_description: OutletSensorDescription

    def __init__(
        self, coordinator: WattboxCoordinator, desc: OutletSensorDescription, outlet: int
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, f"outlet_{desc.key}", outlet)
        self.entity_description = desc
        self._attr_name = f"{self._outlet_name} {desc.name_suffix}"

    @property
    def native_value(self) -> float | None:
        """The reading."""
        power = self.coordinator.data.outlet_power.get(self._outlet)
        return self.entity_description.value_fn(power) if power else None
