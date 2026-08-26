"""What every Intelleta entity has in common. Cards 88 and 97.

Kept in one place so the rules below are written once. Four control platforms
each re-implementing "which device am I" and "how do I send a command" is four
chances to get one of them subtly different.
"""

from __future__ import annotations

import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import API_BASE_URL, DOMAIN
from .controls import Command

_LOGGER = logging.getLogger(__name__)


class IntellettaEntity(CoordinatorEntity):
    """One entity belonging to one cube."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._key = key

        # ⛔ STABLE ACROSS RESTARTS, RENAMES AND ADDRESS CHANGES. Home Assistant
        # keys everything it remembers to this string — history, which room the
        # entity is in, every customisation. Deriving it from anything that can
        # change would silently orphan the customer's history the first time
        # that thing changed.
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def _readings(self):
        return (self.coordinator.data or {}).get(self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.devices.get(self._device_id)
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            # ⚠ FROM THE ACCOUNT, never from anything announced on the network.
            # See matching.py for why that distinction matters.
            name=getattr(device, "name", None) or self._device_id,
            manufacturer="Intelleta",
            model=getattr(device, "device_type", None) or "aqm-cube",
            sw_version=getattr(device, "firmware_version", None),
        )

    @property
    def available(self) -> bool:
        """⚠ AVAILABLE MEANS "we have heard from this cube", not "this control
        has a confirmed value". A control whose applied value is still unknown
        is perfectly usable — you can still move it — and showing it unavailable
        would read as broken hardware."""
        if not self.coordinator.last_update_success:
            return False
        return self._device_id in (self.coordinator.data or {})

    async def _async_send(self, commands: list[Command]) -> None:
        """Send commands to this cube, in order.

        ⛔ IN ORDER, AND STOPPING ON THE FIRST FAILURE. Brightness sends the mode
        and then the level (card 97); firing them concurrently, or carrying on
        after the mode was refused, would apply a level the cube then ignores —
        the silent half-application this ordering exists to prevent.

        ⚠ NO OPTIMISTIC UPDATE AFTERWARDS. The control keeps showing what the
        cube last SAID until the cube says something new. Writing the requested
        value into the entity here would be exactly the "screen says saved,
        nothing changed" defect the card is about.
        """
        session = self.coordinator._session  # noqa: SLF001
        key = self.coordinator._key  # noqa: SLF001

        for command in commands:
            body = {"command": command.command, **command.params}
            try:
                async with session.post(
                    f"{API_BASE_URL}/integration/devices/{self._device_id}/commands",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                ) as response:
                    if response.status >= 400:
                        _LOGGER.error(
                            "%s refused for %s: HTTP %s",
                            command.command, self._device_id, response.status,
                        )
                        return
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("%s failed for %s: %s", command.command, self._device_id, err)
                return

        # Ask the cube to speak now rather than waiting out its interval, so the
        # applied value arrives sooner. ⚠ Best effort: if this fails the control
        # simply catches up on the next poll.
        await self.coordinator.async_request_refresh()
