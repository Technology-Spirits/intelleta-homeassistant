"""The screen. Card 97."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controls import applied_value, set_screen_power
from .entity import IntellettaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IntellettaScreenSwitch(coordinator, device_id)
        for device_id, device in coordinator.devices.items()
        # ⛔ Only a cube that declares a screen gets a screen switch.
        if "panel" in (device.capabilities or ())
    )


class IntellettaScreenSwitch(IntellettaEntity, SwitchEntity):
    def __init__(self, coordinator, device_id) -> None:
        super().__init__(coordinator, device_id, "screen_power")
        self.entity_description = SwitchEntityDescription(
            key="screen_power", name="Screen"
        )

    @property
    def is_on(self) -> bool | None:
        """⚠ None IS A THIRD ANSWER AND MUST REMAIN REACHABLE.

        "We do not know whether the screen is on" is a different statement from
        "it is off", and a switch that renders unknown as off tells the customer
        something untrue about their own cube — then invites them to "fix" it by
        toggling something that was never wrong.
        """
        value = applied_value(self._readings, "screen_power")
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        await self._async_send(set_screen_power(True))

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        await self._async_send(set_screen_power(False))
