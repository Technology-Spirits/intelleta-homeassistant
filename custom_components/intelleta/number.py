"""Brightness and volume. Card 97."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controls import applied_value, set_brightness, set_volume
from .entity import IntellettaEntity

# ⛔ CAPABILITY-GATED. A brightness control on a cube with no screen, or a volume
# control on one that cannot speak, is a control that does nothing — and the
# customer blames the product, not the missing part.
_NUMBERS = (
    ("brightness", "Brightness", "panel", set_brightness),
    ("volume", "Volume", "voice", set_volume),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device_id, device in coordinator.devices.items():
        for key, name, capability, builder in _NUMBERS:
            if capability in (device.capabilities or ()):
                entities.append(
                    IntellettaNumber(coordinator, device_id, key, name, builder)
                )
    async_add_entities(entities)


class IntellettaNumber(IntellettaEntity, NumberEntity):
    """A percentage the customer can set, showing what the cube applied."""

    def __init__(self, coordinator, device_id, key, name, builder) -> None:
        super().__init__(coordinator, device_id, key)
        self._builder = builder
        self.entity_description = NumberEntityDescription(
            key=key,
            name=name,
            native_min_value=0,
            native_max_value=100,
            native_step=1,
            native_unit_of_measurement="%",
        )

    @property
    def native_value(self) -> float | None:
        """⛔ WHAT THE CUBE APPLIED, OR UNKNOWN. Never the last request — see
        controls.applied_value for why that distinction is the whole card."""
        value = applied_value(self._readings, self._key)
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self._async_send(self._builder(int(value)))
