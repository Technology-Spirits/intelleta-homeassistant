"""What the customer shares with Intelleta, and when it is sent to the account.

The customer picks things on the integration's options screen ("Share with
Intelleta"). Only those leave the home, and for each one only four facts:
Home Assistant's own id for it, its name, its kind and its room. The account
keeps a pick by the id, so a rename in Home Assistant never breaks a pick.

The same message carries what a device needs to reach this integration on the
home network: the address and port the integration listens on, and the public
half of its own key. And the integration's version, because a version we
release is not a version anyone is running.

⛔ THE COST RULE. The set is sent once at each start and then only when
something in it changed. Checking every minute is free (it happens inside
Home Assistant); sending is not. `SharedSetSender` holds that rule and has its
own tests.

⚠ THIS MODULE IMPORTS NOTHING, Home Assistant included, so it is tested on any
machine. Reading names and rooms out of Home Assistant is `share.py`'s job.
"""

from __future__ import annotations

import asyncio
import copy
import ipaddress
import re
import time
from collections.abc import Awaitable, Callable, Iterable

# The kinds a customer can share: things that can be switched, opened, run or
# set. These are Home Assistant's own domains, and they are exactly the kinds
# a device knows what to do with. Nothing inside this list is held back because
# of its kind; the customer chooses.
SHAREABLE_KINDS: tuple[str, ...] = (
    "light",
    "switch",
    "fan",
    "cover",
    "lock",
    "climate",
    "media_player",
    "scene",
)

# ── A whole device shared as ONE thing ─────────────────────────────────────
#
# The customer can also pick a whole Home Assistant device, for example a
# four-gang wall switch. It is shared as ONE thing under the device's own
# name: one row in the app, one of the six places on an Intelleta device, and
# one request switches every light and switch on it.
#
# Its id is made here from Home Assistant's own id for the device, in the same
# form as an entity's id, so the account, the app and an Intelleta device carry
# it like any other thing. Only this integration knows it stands for several
# (receiver.py turns it back into its members when a request arrives).
#
# ⛔ ALWAYS THE KIND `switch`, whatever is on the device. The account keeps a
# pick by the id, and an id that changed with what the device holds would drop
# the pick. On and off are the only things a whole device is asked to do.
WHOLE_DEVICE_KIND = "switch"
WHOLE_DEVICE_MEMBER_KINDS: tuple[str, ...] = ("light", "switch")
_WHOLE_PREFIX = f"{WHOLE_DEVICE_KIND}.intelleta_whole_"
_DEVICE_ID_RE = re.compile(r"^[a-z0-9]+\Z")

# The state of a whole device whose members do not all agree (or where some
# cannot be read). It is neither on nor off, so it never counts as done.
WHOLE_MIXED = "mixed"
_NO_STATE = (None, "unavailable", "unknown")


def whole_device_entity(device_id: object) -> str | None:
    """The id a whole device is shared under, or None for a device id that
    cannot be carried in one (never seen from Home Assistant, which makes
    its device ids from lower-case letters and digits)."""
    if not isinstance(device_id, str) or _DEVICE_ID_RE.match(device_id) is None:
        return None
    return f"{_WHOLE_PREFIX}{device_id}"


def whole_device_id(entity: object) -> str | None:
    """The Home Assistant device id behind a whole-device thing, or None when
    `entity` is an ordinary thing."""
    if not isinstance(entity, str) or not entity.startswith(_WHOLE_PREFIX):
        return None
    device_id = entity[len(_WHOLE_PREFIX):]
    return device_id if _DEVICE_ID_RE.match(device_id) else None


def whole_state(states: Iterable[str | None]) -> str | None:
    """The one state of a whole device, from its members' states.

    ⛔ "ON" MEANS ALL OF THEM, AND SO DOES "OFF". A device with three of four
    lights on is `mixed`, which is neither, so the gate never says "done"
    while one is still as it was. A member that cannot be read keeps the whole
    device `mixed` for the same reason. None when it has no members;
    `unavailable` when none of them can be read.
    """
    members = list(states)
    if not members:
        return None
    readable = [state for state in members if state not in _NO_STATE]
    if not readable:
        return "unavailable"
    if len(readable) == len(members):
        if all(state == "on" for state in readable):
            return "on"
        if all(state == "off" for state in readable):
            return "off"
    return WHOLE_MIXED


def split_scenes(entity_ids: Iterable[str]) -> tuple[list[str], list[str]]:
    """The saved list as the screen shows it: (things, scenes), each in the
    order it was saved."""
    things: list[str] = []
    scenes: list[str] = []
    for entity_id in entity_ids:
        (scenes if entity_id.split(".", 1)[0] == "scene" else things).append(entity_id)
    return things, scenes


def merge_picks(*lists: Iterable[str] | None) -> list[str]:
    """The screen's lists as one saved list, each id once, in order."""
    merged: list[str] = []
    for picked in lists:
        for item in picked or ():
            if item not in merged:
                merged.append(item)
    return merged


# The UDP port the integration listens on for a device's request. The same
# port the devices already use among themselves on the home network.
GATE_UDP_PORT = 41846

# The account's own bounds. A thing outside them would make the account refuse
# the WHOLE set, so it is left out here (and logged by the caller) instead.
#
# A thing inside them but past what can be picked (an entity or a name over 96
# bytes, a name with a control byte) IS sent: the account stores it as not
# pickable, so the app can show it and say why. Whether a thing can be picked
# is the account's call, not this module's.
MAX_SHARED_THINGS = 500
MAX_ENTITY_BYTES = 255
MAX_STORED_NAME_BYTES = 255
MAX_ROOM_BYTES = 96

# After the account answered that it has no route for the shared set (its side
# not deployed yet), the same set is asked again this often, so a home whose
# set never changes still reaches the account once it has the route.
ROUTE_MISSING_RETRY_S = 3600

_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\Z")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _utf8_len(text: str) -> int | None:
    """Its length in UTF-8, or None for text that is not well formed (half of
    a surrogate pair), which the account refuses."""
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError:
        return None


def _entity_ok(entity: object) -> bool:
    if not isinstance(entity, str) or _ENTITY_RE.match(entity) is None:
        return False
    size = _utf8_len(entity)
    return size is not None and 3 <= size <= MAX_ENTITY_BYTES


def _name_ok(name: object) -> bool:
    if not isinstance(name, str):
        return False
    size = _utf8_len(name)
    return size is not None and 1 <= size <= MAX_STORED_NAME_BYTES


def _room(room: object) -> str | None:
    if not isinstance(room, str) or not room:
        return None
    size = _utf8_len(room)
    if size is None or size > MAX_ROOM_BYTES or _CONTROL_RE.search(room):
        return None
    return room


def gate_address_ok(addr: object) -> bool:
    """Whether `addr` is a home-network IPv4 address a device can reach: the
    account refuses a loopback, unspecified, multicast or broadcast one."""
    if not isinstance(addr, str):
        return False
    try:
        parsed = ipaddress.IPv4Address(addr)
    except ValueError:
        return False
    return not (
        parsed.is_loopback
        or parsed.is_unspecified
        or parsed.is_multicast
        or parsed == ipaddress.IPv4Address("255.255.255.255")
    )


def shareable(entity: str, name: object) -> bool:
    """Whether one thing can be sent as it is. For the caller's log."""
    return (
        _entity_ok(entity)
        and entity.split(".", 1)[0] in SHAREABLE_KINDS
        and _name_ok(name)
    )


def build_shared_body(
    *,
    integration_version: str,
    gate_addr: str,
    gate_port: int,
    gate_pubkey: str,
    things: Iterable[dict],
) -> dict:
    """The body of `PUT /integration/shared`.

    `things` are plain dicts with `entity`, `name` and `room` (anything else in
    them is ignored, so nothing extra can leave by accident). The kind is the
    entity's own domain. The result is sorted by entity, so the same set always
    makes the same body and an unchanged set compares equal.
    """
    chosen: dict[str, dict] = {}
    for raw in things:
        entity = raw.get("entity")
        name = raw.get("name")
        if not shareable(entity, name) or entity in chosen:
            continue
        chosen[entity] = {
            "entity": entity,
            "name": name,
            "kind": entity.split(".", 1)[0],
            "room": _room(raw.get("room")),
        }

    ordered = [chosen[entity] for entity in sorted(chosen)][:MAX_SHARED_THINGS]
    return {
        "integration_version": integration_version,
        "gate": {"addr": gate_addr, "port": gate_port, "pubkey": gate_pubkey},
        "things": ordered,
    }


class SharedSetSender:
    """Sends the shared set when it changed, and only then.

    One sender lives for one start of the integration. The first body it is
    given is always sent (once per start); after that a body equal to the last
    one the account accepted is not sent again.

    What the account answered decides what happens to a body it did not take:
      * an outage (any error not named below): not remembered, so the next
        check sends it again;
      * `missing` (the account has no route for it yet): remembered as tried,
        and asked again only when it changes or every `ROUTE_MISSING_RETRY_S`,
        because the account side can ship later than the integration;
      * `rejected` (the account refuses this body for good, or the key):
        remembered as tried and raised, so the caller can say why; asked again
        only when it changes. A new key means a new start, and a new sender.

    The exception types are the caller's (its account client's), so this
    module still imports nothing.
    """

    def __init__(
        self,
        *,
        missing: tuple[type[BaseException], ...] = (),
        rejected: tuple[type[BaseException], ...] = (),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._missing = missing
        self._rejected = rejected
        self._clock = clock
        self._last: dict | None = None
        self._ask_again_at: float | None = None
        self._lock = asyncio.Lock()

    async def async_push(
        self, body: dict, put: Callable[[dict], Awaitable[object]]
    ) -> bool:
        """Send `body` with `put` if it differs from the last one sent.

        Returns True when it was sent. A `rejected` error is raised after the
        body is recorded; any other error but `missing` is raised and the body
        is not recorded.
        """
        async with self._lock:
            now = self._clock()
            if (
                self._last is not None
                and body == self._last
                and (self._ask_again_at is None or now < self._ask_again_at)
            ):
                return False
            snapshot = copy.deepcopy(body)
            try:
                await put(snapshot)
            except self._missing:
                self._last = snapshot
                self._ask_again_at = now + ROUTE_MISSING_RETRY_S
                return False
            except self._rejected:
                self._last = snapshot
                self._ask_again_at = None
                raise
            self._last = snapshot
            self._ask_again_at = None
            return True
