"""The Intelleta integration. Card 88."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CloudClient
from .const import API_BASE_URL, CONF_CREDENTIAL, DOMAIN
from .coordinator import IntellettaCoordinator
from .receiver import async_attach_gate, gate_listening, stop_gate
from .share import SharePublisher, async_remove_gate_key

_LOGGER = logging.getLogger(__name__)

# ⚠ EVERY PLATFORM LISTED HERE MUST HAVE ITS FILE. Listing one before the file
# exists makes Home Assistant log a failure on every startup for something
# nobody has built — which is why this list grew with card 97 rather than ahead
# of it.
PLATFORMS: list[Platform] = [
    Platform.SENSOR,         # card 88 — the readings
    Platform.BINARY_SENSOR,  # card 88 — is the cube there at all
    Platform.NUMBER,   # card 97 — brightness, volume
    Platform.SELECT,   # card 97 — brightness mode, reporting interval
    Platform.SWITCH,   # card 97 — the screen
    Platform.BUTTON,   # card 97 — restart, refresh now
]


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

    # ── The gate: devices on the home network ask here to switch a thing ──
    #
    # It judges each request with the devices' keys and lists the readings'
    # poll last read from the account, and what the customer shares below.
    # Started first, so the first check below finds it listening.
    # ⛔ A gate that cannot start must not cost the customer their readings.
    try:
        await async_attach_gate(hass, entry, coordinator)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("the home control gate could not start")

    # ── What the customer shares (the "Share with Intelleta" screen) ──
    #
    # Checked once now, when the screen is saved, and every minute after; sent
    # only when something changed, and only while the gate is listening.
    # Started after the readings and never awaited here, so a failure to send
    # cannot cost the customer them.
    publisher = SharePublisher(
        hass,
        entry,
        CloudClient(async_get_clientsession(hass), API_BASE_URL, entry.data[CONF_CREDENTIAL]),
        gate_listening=lambda: gate_listening(hass),
    )
    publisher.start()

    async def _options_saved(_hass: HomeAssistant, _entry: ConfigEntry) -> None:
        await publisher.async_check()

    entry.async_on_unload(entry.add_update_listener(_options_saved))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The integration was removed: its own key pair goes with it.

    Set up again, it makes a new key, which reaches the devices through the
    account. Kept while another entry still uses it.
    """
    remaining = [
        other
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ]
    if not remaining:
        # A gate still running (its entry failed to unload) would sign with
        # the removed key while a new one is shared: stopped with its key.
        stop_gate(hass)
        await async_remove_gate_key(hass)
