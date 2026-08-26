"""Restart, and ask now. Card 97."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controls import refresh_now, restart
from .entity import IntellettaEntity

# ⚠ THERE IS NO IDENTIFY BUTTON HERE, AND THAT IS A FINDING RATHER THAN AN
# OMISSION. `identify` exists in the DEVICE contract but is NOT in the cloud's
# command table, so the cloud refuses it today. Card 97 lists an identify
# button; the command has to be added on the cloud side first.
#
# ⛔ Building it anyway would ship a button that always fails, which is worse
# than a button that does not exist — the customer cannot tell "not built" from
# "broken", and will report the second.
_BUTTONS = (
    ("restart", "Restart", restart, EntityCategory.DIAGNOSTIC),
    ("refresh", "Refresh now", refresh_now, EntityCategory.DIAGNOSTIC),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IntellettaButton(coordinator, device_id, key, name, builder, category)
        for device_id in coordinator.devices
        for key, name, builder, category in _BUTTONS
    )


class IntellettaButton(IntellettaEntity, ButtonEntity):
    def __init__(self, coordinator, device_id, key, name, builder, category) -> None:
        super().__init__(coordinator, device_id, key)
        self._builder = builder
        self.entity_description = ButtonEntityDescription(
            key=key, name=name, entity_category=category
        )

    async def async_press(self) -> None:
        await self._async_send(self._builder())
