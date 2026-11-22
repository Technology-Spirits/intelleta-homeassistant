"""Sending what the customer shares to the account.

The Home Assistant side of `sharing.py`: it reads the picked things' names and
rooms out of Home Assistant, keeps the integration's own key pair in Home
Assistant's storage, finds the address devices can reach the integration on,
and hands the result to `sharing.SharedSetSender`, which decides whether
anything is actually sent.

When it checks:
  * once at each start (and that first check always sends);
  * when the customer saves the "Share with Intelleta" screen;
  * every minute, so a rename or a new room in Home Assistant reaches the
    account within a minute. A check that finds nothing changed sends nothing.

⛔ NOTHING HERE MAY STOP THE READINGS. A failure to send is logged and tried
again at the next check; it never fails the integration's setup.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.components import network
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from . import api, sharing
from .const import CONF_SHARED, CONF_SHARED_DEVICES, DOMAIN
from .gate_key import new_private_key_pem, usable_key_pair

_LOGGER = logging.getLogger(__name__)

CHECK_EVERY = timedelta(seconds=60)

# ⛔ ONE KEY PAIR PER HOME ASSISTANT, kept in its own storage folder and never
# sent anywhere. Removing the integration removes it; setting it up again makes
# a new one, which reaches the devices through the account.
GATE_KEY_STORE = f"{DOMAIN}.gate_key"
GATE_KEY_STORE_VERSION = 1


@dataclass(frozen=True)
class GateKey:
    private_pem: str
    public_b64: str
    # The key to sign with, read once from `private_pem` (off the loop).
    private_key: object = field(compare=False, repr=False, default=None)


_GATE_KEY_CACHE = f"{DOMAIN}_gate_key_loaded"
_GATE_KEY_LOCK = f"{DOMAIN}_gate_key_lock"


async def async_load_gate_key(hass: HomeAssistant) -> GateKey:
    """The integration's key pair: the stored one, or a new one made once.

    ⛔ ONE LOAD FOR EVERY CALLER. The shared set (which sends the public half)
    and the gate (which signs with the private half) both ask for it at
    start. Two callers making a key at the same moment would leave the
    devices told one key and the answers signed with another, so the first
    load is shared and kept until the key is removed.
    """
    cached = hass.data.get(_GATE_KEY_CACHE)
    if cached is not None:
        return cached
    lock = hass.data.setdefault(_GATE_KEY_LOCK, asyncio.Lock())
    async with lock:
        cached = hass.data.get(_GATE_KEY_CACHE)
        if cached is None:
            cached = await _async_read_or_make_gate_key(hass)
            hass.data[_GATE_KEY_CACHE] = cached
    return cached


async def _async_read_or_make_gate_key(hass: HomeAssistant) -> GateKey:
    """⚠ Reading a key checks it, which is slow on a small computer: every
    read and every new key runs off the event loop, and each once."""
    store: Store = Store(hass, GATE_KEY_STORE_VERSION, GATE_KEY_STORE, private=True)
    stored = await store.async_load()
    pem = stored.get("private_key") if isinstance(stored, dict) else None
    pair = await hass.async_add_executor_job(usable_key_pair, pem)
    if pair is None:
        if stored is not None:
            _LOGGER.warning("the stored gate key could not be read; making a new one")
        pem = await hass.async_add_executor_job(new_private_key_pem)
        await store.async_save({"private_key": pem})
        pair = await hass.async_add_executor_job(usable_key_pair, pem)
        if pair is None:  # pragma: no cover - a key just made always reads
            raise HomeAssistantError("a new gate key could not be read back")
    private_key, public_b64 = pair
    return GateKey(private_pem=pem, public_b64=public_b64, private_key=private_key)


async def async_remove_gate_key(hass: HomeAssistant) -> None:
    hass.data.pop(_GATE_KEY_CACHE, None)
    await Store(hass, GATE_KEY_STORE_VERSION, GATE_KEY_STORE, private=True).async_remove()


def collect_things(hass: HomeAssistant, entity_ids: list[str]) -> list[dict]:
    """Each picked thing's id, Home Assistant's own name for it, and its room.

    The room is the thing's own area, else its device's area. A thing that no
    longer exists in Home Assistant is left out, so it leaves the account.
    """
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    areas = ar.async_get(hass)

    things: list[dict] = []
    for entity_id in entity_ids:
        entry = entities.async_get(entity_id)
        state = hass.states.get(entity_id)
        if entry is None and state is None:
            continue

        if state is not None:
            name = state.name
        else:
            name = entry.name or entry.original_name or entity_id

        area_id = entry.area_id if entry is not None else None
        if area_id is None and entry is not None and entry.device_id:
            device = devices.async_get(entry.device_id)
            area_id = device.area_id if device is not None else None
        area = areas.async_get_area(area_id) if area_id else None

        things.append(
            {"entity": entity_id, "name": name, "room": area.name if area else None}
        )
    return things


def whole_members(hass: HomeAssistant, device_id: str) -> list[str]:
    """The lights and switches a whole device stands for, as it is now.

    Left out: anything that is not a light or a switch, a settings or
    diagnostic toggle, anything the customer disabled or hidden in Home
    Assistant (their way to leave one out), and Intelleta's own entities.
    Sorted, so the same device always gives the same list.
    """
    entities = er.async_get(hass)
    members = [
        entry.entity_id
        for entry in er.async_entries_for_device(entities, device_id)
        if entry.domain in sharing.WHOLE_DEVICE_MEMBER_KINDS
        and entry.entity_category is None
        and entry.hidden_by is None
        and entry.platform != DOMAIN
    ]
    return sorted(members)


def collect_whole_things(hass: HomeAssistant, device_ids: list[str]) -> list[dict]:
    """Each picked whole device as ONE thing: its made-up id, the device's
    own name and its room.

    A device that no longer exists, has no name, or holds no light or switch
    is left out, so it leaves the account.
    """
    devices = dr.async_get(hass)
    areas = ar.async_get(hass)

    things: list[dict] = []
    for device_id in device_ids:
        entity = sharing.whole_device_entity(device_id)
        device = devices.async_get(device_id) if entity is not None else None
        if device is None:
            continue
        name = device.name_by_user or device.name
        if not name or not whole_members(hass, device_id):
            continue
        area = areas.async_get_area(device.area_id) if device.area_id else None
        things.append({"entity": entity, "name": name, "room": area.name if area else None})
    return things


def shared_ids(options: dict) -> list[str]:
    """Every id the customer shares: the picked things, then one id for each
    whole device. What the gate allows and what the account is told are both
    built from this, so they cannot differ."""
    whole = [
        entity
        for entity in map(sharing.whole_device_entity, options.get(CONF_SHARED_DEVICES, []))
        if entity is not None
    ]
    return sharing.merge_picks(options.get(CONF_SHARED, []), whole)


async def async_gate_address(hass: HomeAssistant) -> str | None:
    """The home-network IPv4 address devices can reach this Home Assistant on."""
    try:
        addr = await network.async_get_source_ip(hass)
    except HomeAssistantError:
        return None
    return addr if sharing.gate_address_ok(addr) else None


class SharePublisher:
    """One per config entry, for one start of the integration.

    ⛔ THE GATE IS ONLY REPORTED WHILE IT IS LISTENING. The set carries the
    address and port devices send their requests to; reporting them for a
    listener that could not open would send every request into the void.
    `gate_listening` says whether it is; until it is, nothing is sent.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        cloud: api.CloudClient,
        *,
        gate_listening: Callable[[], bool],
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._cloud = cloud
        self._gate_listening = gate_listening
        self._sender = sharing.SharedSetSender(
            missing=(api.RouteMissing,), rejected=(api.Rejected,)
        )
        self._key: GateKey | None = None
        self._version: str | None = None
        self._no_address_logged = False

    def start(self) -> None:
        """Check now, then every minute, until the entry unloads."""
        self._entry.async_create_background_task(
            self._hass, self.async_check(), f"{DOMAIN} shared set"
        )
        self._entry.async_on_unload(
            async_track_time_interval(self._hass, self._async_tick, CHECK_EVERY)
        )

    async def _async_tick(self, _now) -> None:  # noqa: ANN001
        await self.async_check()

    async def async_check(self) -> None:
        """Build the set as it is now; send it if it changed."""
        try:
            if self._key is None:
                self._key = await async_load_gate_key(self._hass)
            if self._version is None:
                integration = await async_get_integration(self._hass, DOMAIN)
                self._version = str(integration.version)

            if not self._gate_listening():
                _LOGGER.debug("the gate is not listening; nothing is reported until it is")
                return

            addr = await async_gate_address(self._hass)
            if addr is None:
                if not self._no_address_logged:
                    _LOGGER.warning(
                        "no home-network address found for Home Assistant; "
                        "what is shared is sent once one is found"
                    )
                    self._no_address_logged = True
                return
            self._no_address_logged = False

            picked = list(self._entry.options.get(CONF_SHARED, []))
            things = collect_things(self._hass, picked)
            things += collect_whole_things(
                self._hass, list(self._entry.options.get(CONF_SHARED_DEVICES, []))
            )
            for thing in things:
                if not sharing.shareable(thing["entity"], thing["name"]):
                    _LOGGER.debug("%s cannot be shared as it is; left out", thing["entity"])

            body = sharing.build_shared_body(
                integration_version=self._version,
                gate_addr=addr,
                gate_port=sharing.GATE_UDP_PORT,
                gate_pubkey=self._key.public_b64,
                things=things,
            )
            if await self._sender.async_push(body, self._cloud.async_put_shared):
                _LOGGER.debug("%d shared thing(s) sent to the account", len(body["things"]))
        except api.AuthFailed:
            # The readings' own poll turns a refused key into the reauth
            # prompt; saying it twice helps nobody. Not sent again until the
            # set changes or the integration starts again with a new key.
            _LOGGER.debug("the key was refused while sending the shared set")
        except api.Rejected as err:
            _LOGGER.warning(
                "the account refused what is shared (field: %s); it is sent again "
                "when something in it changes",
                err.field or "not named",
            )
        except api.CloudUnavailable as err:
            _LOGGER.debug("could not send the shared set (%s); trying again", err)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("unexpected error while sending the shared set")
