"""Whether a cube is there at all. Card 88.

⛔ THE THRESHOLD IS THE PLATFORM'S OWN, NOT A NEW ONE. Our cloud's offline
checker calls a cube offline after five minutes without a word, and that is the
number the customer's alerts already use. Choosing a different one here would
give them two answers to "is my cube online" — one in our app, one in Home
Assistant — disagreeing for minutes at a time, with nothing on either screen to
explain why. That is the kind of discrepancy a customer reports as a bug in
both products.
"""

from __future__ import annotations

import time

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import IntellettaEntity

# Matches OFFLINE_THRESHOLD_SECONDS in the cloud's offline checker. ⚠ If that
# ever changes, this follows it — two numbers for one question is the defect.
OFFLINE_AFTER_SECONDS = 300


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IntellettaOnline(coordinator, device_id) for device_id in coordinator.devices
    )


class IntellettaOnline(IntellettaEntity, BinarySensorEntity):
    """On when the cube has spoken recently."""

    def __init__(self, coordinator, device_id) -> None:
        super().__init__(coordinator, device_id, "online")
        self.entity_description = BinarySensorEntityDescription(
            key="online",
            name="Online",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
        )

    @property
    def available(self) -> bool:
        """⛔ ALWAYS AVAILABLE WHILE THE ACCOUNT IS REACHABLE, WHICH IS THE WHOLE
        POINT OF THIS ENTITY.

        Every other entity here goes unavailable when its cube goes quiet — that
        is honest for a reading. But an online sensor that goes unavailable when
        the cube goes offline can never say "offline", which is the one thing it
        exists to say. It would show as unknown at exactly the moment somebody
        checks it.
        """
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        """True if the cube has been heard from inside the threshold.

        ⚠ THE MOST RECENT OF TWO CLOCKS, deliberately. A reading we hold locally
        is the strongest evidence a cube is alive; the account's `last_seen` is
        what the cloud knows. Taking the later of them means a cube talking to us
        over the home network still counts as online when the cloud has not
        heard from it — which is exactly the case the local path creates, and
        reporting it offline then would be wrong on the customer's own screen
        while their cube sits there working.
        """
        newest = 0

        readings = self._readings
        if readings is not None and readings.timestamp:
            newest = max(newest, int(readings.timestamp))

        device = self.coordinator.devices.get(self._device_id)
        last_seen = getattr(device, "last_seen", 0) or 0
        if isinstance(last_seen, int):
            newest = max(newest, last_seen)

        if newest <= 0:
            # ⛔ NEVER HEARD FROM AT ALL IS UNKNOWN, NOT OFFLINE. A cube claimed
            # a minute ago and not yet powered on has not failed; saying
            # "offline" would send somebody looking for a fault that does not
            # exist yet.
            return None

        return (time.time() - newest) < OFFLINE_AFTER_SECONDS
