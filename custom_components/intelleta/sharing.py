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
import re
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

# The UDP port the integration listens on for a device's request. The same
# port the devices already use among themselves on the home network.
GATE_UDP_PORT = 41846

# The account's own bounds. A thing outside them would make the account refuse
# the WHOLE set, so it is left out here (and logged by the caller) instead.
MAX_SHARED_THINGS = 500
MAX_ENTITY_BYTES = 96
MAX_STORED_NAME_BYTES = 255
MAX_ROOM_BYTES = 96

_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class RouteMissing(Exception):
    """The account has no place for the shared set yet (it answered 404).

    Distinct from an outage: retrying every minute would cost a request a
    minute in every home and change nothing.
    """


def _entity_ok(entity: object) -> bool:
    return (
        isinstance(entity, str)
        and 3 <= len(entity.encode("utf-8")) <= MAX_ENTITY_BYTES
        and _ENTITY_RE.match(entity) is not None
    )


def _name_ok(name: object) -> bool:
    return (
        isinstance(name, str)
        and 1 <= len(name.encode("utf-8")) <= MAX_STORED_NAME_BYTES
        and _CONTROL_RE.search(name) is None
    )


def _room(room: object) -> str | None:
    if not isinstance(room, str) or not room:
        return None
    if len(room.encode("utf-8")) > MAX_ROOM_BYTES or _CONTROL_RE.search(room):
        return None
    return room


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
    one the account accepted is not sent again. A send that fails is not
    remembered, so the next check sends it. A body the account has no route
    for is remembered as tried, so it is not asked again until it changes.
    """

    def __init__(self) -> None:
        self._last: dict | None = None
        self._lock = asyncio.Lock()

    async def async_push(
        self, body: dict, put: Callable[[dict], Awaitable[object]]
    ) -> bool:
        """Send `body` with `put` if it differs from the last one sent.

        Returns True when it was sent. Errors from `put` other than
        `RouteMissing` are raised to the caller, and the body is not recorded.
        """
        async with self._lock:
            if self._last is not None and body == self._last:
                return False
            snapshot = copy.deepcopy(body)
            try:
                await put(snapshot)
            except RouteMissing:
                self._last = snapshot
                return False
            self._last = snapshot
            return True
