"""The gate's listener on the home network, and its door into Home Assistant.

`gate.py` holds every rule. This file:

  * opens the UDP listener (one per Home Assistant, on the port reported to
    the account with the shared set);
  * tells the gate, for a device id, the device's key and list as the account
    last gave them (the readings' own once-a-minute read of
    `GET /integration/devices`, kept when the account cannot be reached) and
    what the customer shares on the "Share with Intelleta" screen;
  * reads states, calls services and watches state changes for the gate.

⛔ NOTHING HERE MAY STOP THE READINGS. If the port cannot be opened the error
is logged and the integration carries on without the gate.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from cryptography.hazmat.primitives import serialization
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from . import gate, sharing
from .const import CONF_SHARED, DOMAIN
from .share import async_load_gate_key

_LOGGER = logging.getLogger(__name__)

GATE_DATA = f"{DOMAIN}_gate"
_GATE_LOCK = f"{DOMAIN}_gate_lock"


class HassHome:
    """gate.Home on a real Home Assistant."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def state(self, entity: str) -> str | None:
        state = self._hass.states.get(entity)
        return state.state if state is not None else None

    async def call(self, domain: str, service: str, entity: str) -> None:
        await self._hass.services.async_call(
            domain, service, {"entity_id": entity}, blocking=True
        )

    def watch(self, entity: str, on_change: Callable[[str | None], None]) -> Callable[[], None]:
        @callback
        def _changed(event: Event) -> None:
            new = event.data.get("new_state")
            on_change(new.state if new is not None else None)

        return async_track_state_change_event(self._hass, [entity], _changed)


class _Listener(asyncio.DatagramProtocol):
    def __init__(self, receiver: GateReceiver) -> None:
        self._receiver = receiver

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        self._receiver.on_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("home control listener: %s", exc)


class GateReceiver:
    """The one gate in this Home Assistant, shared by every Intelleta entry."""

    def __init__(self, hass: HomeAssistant, key: object) -> None:
        self._hass = hass
        home = HassHome(hass)

        async def act(entity: str, kind: str, action: str, limit_s: float) -> tuple[str, str]:
            return await gate.act_on(home, entity, kind, action, limit_s)

        self._gate = gate.Gate(key, lookup=self.lookup, act=act, send=self._send)
        self._entries: dict[str, tuple[ConfigEntry, object]] = {}
        self._transport: asyncio.DatagramTransport | None = None

    # Who the gate holds keys for -------------------------------------------

    def add(self, entry: ConfigEntry, coordinator: object) -> None:
        self._entries[entry.entry_id] = (entry, coordinator)

    def remove(self, entry_id: str) -> bool:
        """Forget an entry; True when no entry is left."""
        self._entries.pop(entry_id, None)
        return not self._entries

    def lookup(self, device_id: str) -> gate.DeviceRecord | None:
        """A device of one of the accounts here, with its key, its list and
        what that account's customer shares. None for anything else."""
        for entry, coordinator in self._entries.values():
            device = getattr(coordinator, "devices", {}).get(device_id)
            if device is not None:
                return gate.device_record(
                    getattr(device, "pubkey", None),
                    getattr(device, "control", ()),
                    entry.options.get(CONF_SHARED, []),
                )
        return None

    # The listener ----------------------------------------------------------

    async def async_start(self, port: int) -> bool:
        try:
            transport, _ = await self._hass.loop.create_datagram_endpoint(
                lambda: _Listener(self), local_addr=("0.0.0.0", port)
            )
        except OSError as err:
            _LOGGER.error(
                "could not listen on UDP port %d (%s); Intelleta devices cannot ask "
                "this Home Assistant to switch things until it can",
                port, err,
            )
            return False
        self._transport = transport
        _LOGGER.debug("home control: listening on UDP port %d", port)
        return True

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def on_datagram(self, data: bytes, addr: tuple) -> None:
        if len(data) > gate.MAX_DATAGRAM:
            return
        self._hass.async_create_background_task(
            self._gate.handle(data, addr), f"{DOMAIN} home control request"
        )

    def _send(self, data: bytes, addr: tuple) -> None:
        if self._transport is not None:
            self._transport.sendto(data, addr)


def _load_private_key(pem: str) -> object:
    return serialization.load_pem_private_key(pem.encode("ascii"), password=None)


async def async_attach_gate(hass: HomeAssistant, entry: ConfigEntry, coordinator: object) -> None:
    """Start the gate if it is not running, and let it judge this entry's
    devices. Stopped when the last entry unloads."""
    lock = hass.data.setdefault(_GATE_LOCK, asyncio.Lock())
    async with lock:
        receiver: GateReceiver | None = hass.data.get(GATE_DATA)
        if receiver is None:
            pem = (await async_load_gate_key(hass)).private_pem
            key = await hass.async_add_executor_job(_load_private_key, pem)
            receiver = GateReceiver(hass, key)
            if not await receiver.async_start(sharing.GATE_UDP_PORT):
                return
            hass.data[GATE_DATA] = receiver
        receiver.add(entry, coordinator)

    @callback
    def _detach() -> None:
        if receiver.remove(entry.entry_id):
            receiver.stop()
            if hass.data.get(GATE_DATA) is receiver:
                hass.data.pop(GATE_DATA, None)

    entry.async_on_unload(_detach)
