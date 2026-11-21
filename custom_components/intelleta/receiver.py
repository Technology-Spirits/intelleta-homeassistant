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
is logged, the integration carries on without the gate, and the port is tried
again every minute. Until it opens, the gate is not reported to the account
(share.py asks `gate_listening`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from . import gate, sharing
from .const import CONF_SHARED, DOMAIN
from .share import async_load_gate_key

_LOGGER = logging.getLogger(__name__)

GATE_DATA = f"{DOMAIN}_gate"
_GATE_LOCK = f"{DOMAIN}_gate_lock"

# How often a port that could not be opened is tried again.
BIND_RETRY = timedelta(seconds=60)


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
        self._retry_unsub: Callable[[], None] | None = None
        self._bind_failure_logged = False
        self._stopped = False

    @property
    def listening(self) -> bool:
        return self._transport is not None

    # Who the gate holds keys for -------------------------------------------

    def add(self, entry: ConfigEntry, coordinator: object) -> None:
        self._entries[entry.entry_id] = (entry, coordinator)

    def remove(self, entry_id: str) -> bool:
        """Forget an entry; True when no entry is left."""
        self._entries.pop(entry_id, None)
        return not self._entries

    def lookup(self, device_id: str) -> gate.DeviceRecord | None:
        """A device of one of the accounts here, with its key, its list and
        what that account's customer shares. None for anything else.

        ⛔ AN ACCOUNT THAT REFUSED THE KEY HOLDS NO DEVICES HERE. Its last list
        is not used: the customer may have disconnected Home Assistant on
        purpose, and the account's clearing of the lists can no longer reach
        the gate."""
        for entry, coordinator in self._entries.values():
            if getattr(coordinator, "key_refused", False):
                continue
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
            if self._stopped:
                return False
            if not self._bind_failure_logged:
                _LOGGER.error(
                    "could not listen on UDP port %d (%s); Intelleta devices cannot ask "
                    "this Home Assistant to switch things until it can. Trying again "
                    "every minute",
                    port, err,
                )
                self._bind_failure_logged = True
            else:
                _LOGGER.debug("UDP port %d still cannot be opened (%s)", port, err)
            return False
        if self._stopped:
            # Stopped while the port was being opened (a retry in flight when
            # the last entry unloaded): a listener kept now would hold the
            # port with nobody to close it, and the next start could not
            # open it.
            transport.close()
            return False
        self._transport = transport
        if self._bind_failure_logged:
            _LOGGER.info("home control: listening on UDP port %d", port)
        else:
            _LOGGER.debug("home control: listening on UDP port %d", port)
        self._bind_failure_logged = False
        return True

    def retry_until_listening(self, port: int) -> None:
        """Try the port again every minute until it opens or the gate stops."""
        if self._retry_unsub is not None:
            return

        async def _retry(_now: object) -> None:
            if self._transport is None and await self.async_start(port):
                self._cancel_retry()

        self._retry_unsub = async_track_time_interval(
            self._hass, _retry, BIND_RETRY, cancel_on_shutdown=True
        )

    def _cancel_retry(self) -> None:
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

    def stop(self) -> None:
        self._stopped = True
        self._cancel_retry()
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def on_datagram(self, data: bytes, addr: tuple) -> None:
        if len(data) > gate.MAX_DATAGRAM:
            return
        # Junk and strangers are dropped here, at once; only a well-formed
        # request from a device the gate holds a key for starts any work.
        screened = self._gate.screen(data, addr)
        if screened is None:
            return
        self._hass.async_create_background_task(
            self._gate.handle_request(*screened, addr), f"{DOMAIN} home control request"
        )

    def _send(self, data: bytes, addr: tuple) -> None:
        if self._transport is not None:
            self._transport.sendto(data, addr)


def gate_listening(hass: HomeAssistant) -> bool:
    """Whether this Home Assistant's gate is listening for devices now."""
    receiver: GateReceiver | None = hass.data.get(GATE_DATA)
    return receiver is not None and receiver.listening


def stop_gate(hass: HomeAssistant) -> None:
    """Stop the gate, whatever entries it still holds. For when its key is
    removed: a gate left running would sign with a key nobody trusts."""
    receiver: GateReceiver | None = hass.data.pop(GATE_DATA, None)
    if receiver is not None:
        receiver.stop()


async def async_attach_gate(hass: HomeAssistant, entry: ConfigEntry, coordinator: object) -> None:
    """Start the gate if it is not running, and let it judge this entry's
    devices. Stopped when the last entry unloads. A port that cannot be opened
    is tried again every minute."""
    lock = hass.data.setdefault(_GATE_LOCK, asyncio.Lock())
    async with lock:
        receiver: GateReceiver | None = hass.data.get(GATE_DATA)
        if receiver is None:
            key = (await async_load_gate_key(hass)).private_key
            receiver = GateReceiver(hass, key)
            hass.data[GATE_DATA] = receiver
            if not await receiver.async_start(sharing.GATE_UDP_PORT):
                receiver.retry_until_listening(sharing.GATE_UDP_PORT)
        receiver.add(entry, coordinator)

    @callback
    def _detach() -> None:
        if receiver.remove(entry.entry_id):
            receiver.stop()
            if hass.data.get(GATE_DATA) is receiver:
                hass.data.pop(GATE_DATA, None)

    entry.async_on_unload(_detach)
