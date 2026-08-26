"""The Intelleta integration. Card 88."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_CREDENTIAL, DOMAIN
from .coordinator import IntellettaCoordinator

_LOGGER = logging.getLogger(__name__)

# ⚠ SENSORS ONLY, FOR NOW. Controls are card 97 and arrive with it. Listing a
# platform before its file exists makes Home Assistant log a failure on every
# startup for something nobody has built.
PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Intelleta from a config entry."""
    coordinator = IntellettaCoordinator(hass, entry.data[CONF_CREDENTIAL])

    # ⛔ THE FIRST REFRESH IS AWAITED, AND ITS FAILURE IS FATAL TO SETUP. Home
    # Assistant will retry the whole entry later. Setting up "successfully" with
    # no data would give the customer a device full of entities that have never
    # had a value — indistinguishable from broken hardware.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
