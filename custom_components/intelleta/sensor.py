"""The readings, as Home Assistant entities. Card 88.

⛔ CREATE ONLY WHAT THE DEVICE DECLARES. The table of what each capability
entitles a cube to is in `capabilities.py`, deliberately free of every import so
it can be tested in a second. This file is the thin adapter that turns those
facts into Home Assistant objects, and it should stay thin: anything with a rule
in it belongs next door.
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .capabilities import SensorSpec, sensors_for
from .const import DOMAIN
from .coordinator import IntellettaCoordinator

# Our plain strings -> Home Assistant's enums.
#
# ⚠ A `.get()` RATHER THAN A LOOKUP THAT RAISES. A capability table entry naming
# a class this version of Home Assistant does not have must cost that one
# entity its special treatment, never the whole integration's startup.
_DEVICE_CLASSES = {
    "pm1": SensorDeviceClass.PM1,
    "pm25": SensorDeviceClass.PM25,
    "pm10": SensorDeviceClass.PM10,
    "carbon_dioxide": SensorDeviceClass.CO2,
    "carbon_monoxide": SensorDeviceClass.CO,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "illuminance": SensorDeviceClass.ILLUMINANCE,
    "signal_strength": SensorDeviceClass.SIGNAL_STRENGTH,
    "data_size": SensorDeviceClass.DATA_SIZE,
    "enum": SensorDeviceClass.ENUM,
}

_STATE_CLASSES = {"measurement": SensorStateClass.MEASUREMENT}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one entity per reading each cube actually has."""
    coordinator: IntellettaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[IntellettaSensor] = []
    for device_id, device in coordinator.devices.items():
        for spec in sensors_for(device.capabilities):
            entities.append(IntellettaSensor(coordinator, device_id, spec))

    async_add_entities(entities)


class IntellettaSensor(CoordinatorEntity, SensorEntity):
    """One reading from one cube."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: IntellettaCoordinator,
        device_id: str,
        spec: SensorSpec,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._spec = spec

        # ⛔ STABLE ACROSS RESTARTS, RENAMES AND ADDRESS CHANGES. Home Assistant
        # keys everything it remembers — history, customisations, which room the
        # entity is in — to this string. Deriving it from anything that can
        # change would silently orphan the customer's history the first time
        # that thing changed.
        self._attr_unique_id = f"{device_id}_{spec.key}"

        self.entity_description = SensorEntityDescription(
            key=spec.key,
            name=spec.name,
            device_class=_DEVICE_CLASSES.get(spec.device_class or ""),
            native_unit_of_measurement=spec.unit,
            state_class=_STATE_CLASSES.get(spec.state_class or ""),
            entity_category=(
                EntityCategory.DIAGNOSTIC if spec.category == "diagnostic" else None
            ),
        )

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.devices.get(self._device_id)
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            # ⚠ THE NAME COMES FROM THE ACCOUNT, never from anything announced
            # on the network — see matching.py for why that matters.
            name=getattr(device, "name", None) or self._device_id,
            manufacturer="Intelleta",
            model=getattr(device, "device_type", None) or "aqm-cube",
            sw_version=getattr(device, "firmware_version", None),
        )

    @property
    def native_value(self):
        """The reading, or None.

        ⛔ None MEANS UNKNOWN AND MUST STAY THAT WAY. A warming carbon-monoxide
        cell omits its field; anything that turned that into 0 would tell the
        customer the air is perfectly clean. `readings.parse` never invents a
        value, and this must never invent one either — no `or 0`, ever.
        """
        readings = (self.coordinator.data or {}).get(self._device_id)
        return readings.get(self._spec.key) if readings else None

    @property
    def available(self) -> bool:
        """⚠ AVAILABLE MEANS "WE HAVE HEARD FROM THIS CUBE", not "this particular
        reading has a value". A sensor that is warming up is available and has
        no value yet — showing it as unavailable would read as broken hardware
        rather than as a sensor doing what it is supposed to do."""
        if not self.coordinator.last_update_success:
            return False
        return self._device_id in (self.coordinator.data or {})
