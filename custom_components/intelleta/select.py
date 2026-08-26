"""How the brightness is governed, and how often the cube speaks. Card 97."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controls import (
    BRIGHTNESS_MODES,
    POLL_INTERVALS,
    applied_value,
    set_brightness_mode,
    set_poll_interval,
)
from .entity import IntellettaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[IntellettaEntity] = []
    for device_id, device in coordinator.devices.items():
        if "panel" in (device.capabilities or ()):
            entities.append(IntellettaBrightnessMode(coordinator, device_id))
        # ⚠ NOT capability-gated: every cube reports on an interval, whatever
        # else it is or is not made of.
        entities.append(IntellettaPollInterval(coordinator, device_id))
    async_add_entities(entities)


class IntellettaBrightnessMode(IntellettaEntity, SelectEntity):
    """Manual, on a schedule, or following the light in the room.

    ⚠ WORTH KNOWING WHILE READING THIS: moving the brightness slider (number.py)
    forces this to manual, because the cube refuses a bare brightness in any
    other mode. So a customer who drags brightness has silently left their
    schedule — intended, but this is the control that shows it happened.
    """

    def __init__(self, coordinator, device_id) -> None:
        super().__init__(coordinator, device_id, "brightness_mode")
        self.entity_description = SelectEntityDescription(
            key="brightness_mode",
            name="Brightness mode",
            options=list(BRIGHTNESS_MODES),
        )

    @property
    def current_option(self) -> str | None:
        value = applied_value(self._readings, "brightness_mode")
        # ⛔ Only a value the cube reported, and only one we recognise. A select
        # showing an option outside its own list is a Home Assistant error, not
        # a display quirk.
        return value if isinstance(value, str) and value in BRIGHTNESS_MODES else None

    async def async_select_option(self, option: str) -> None:
        await self._async_send(set_brightness_mode(option))


class IntellettaPollInterval(IntellettaEntity, SelectEntity):
    """How often the cube speaks.

    ⚠ A SELECT RATHER THAN A NUMBER, ON PURPOSE. The cube accepts exactly four
    intervals and refuses everything else, so a free number box would let the
    customer choose a value that silently does nothing — and leave them
    convinced they had changed something.
    """

    def __init__(self, coordinator, device_id) -> None:
        super().__init__(coordinator, device_id, "poll_interval")
        self.entity_description = SelectEntityDescription(
            key="poll_interval",
            name="Reporting interval",
            options=[str(seconds) for seconds in POLL_INTERVALS],
            entity_category=EntityCategory.CONFIG,
        )

    @property
    def current_option(self) -> str | None:
        value = applied_value(self._readings, "poll_interval")
        if not isinstance(value, (int, float)):
            return None
        option = str(int(value))
        # A cube reporting an interval outside the four is either malfunctioning
        # or newer than this integration. Either way, showing an option that is
        # not in the list is an error rather than information.
        return option if option in self.entity_description.options else None

    async def async_select_option(self, option: str) -> None:
        await self._async_send(set_poll_interval(int(option)))
