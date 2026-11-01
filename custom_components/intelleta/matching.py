"""Joining what the account owns with what is announcing itself. Card 93.

⛔⛔ THIS IS THE SECURITY BOUNDARY OF THE ENTIRE LOCAL PATH.

Two lists arrive from completely different places:

  * from our cloud, behind the customer's sign-in: which cubes this account owns
  * from the local network: which cubes are announcing themselves nearby

Anything on the second list that is not on the first must be **ignored**.
Otherwise a flat-mate's cube, a neighbour's through a thin wall, or something
merely *claiming* to be a cube feeds readings into this customer's house — and
the readings look perfectly ordinary, because they are ordinary readings from
the wrong place. Nobody reports that as a bug. They just quietly distrust the
product.

⛔ THE IDENTIFIER IS NOT A SECRET AND MUST NOT BE TREATED AS ONE. A cube's
identifier comes from its hardware and appears in ordinary places. It proves
*which* cube is speaking; it never proves the speaker is entitled to be heard.
**The account list is the authority. The announcement is only a pointer.**

That distinction is exactly what the platform got wrong twice — an identity
required to be valid and then never consulted — so it is written here, and the
tests fail if the direction is ever reversed.

⚠ Local traffic is unencrypted, by ruling: readings on a home network travel in
the open, as local devices normally do. That is accepted for readings. It does
mean an announcement can be imitated by anything on the same network, which is
precisely why the account list decides and the announcement does not.

⭐ THE ACCOUNT'S OWN ADDRESS COMES FIRST (card 5, 2026-11-01). Every device
reports its home-network address to the account when it starts (the house line,
aqm 846), and the account's device list carries it as `lan_ip`. That address is
turned into an announcement here (`account_announcements`) and goes through the
SAME reconcile as a network sighting, ahead of it — so a device is reached at
the address the account vouches for, a network sighting fills in only for a
device the account has no address for, and the cloud remains the fallback. A
home router drops the multicast group minutes after a device joins (measured
2026-10-22 and again 2026-11-01), so the broadcast alone left every reading on
the cloud road. The authority has not moved: the account list decides both the
device AND, now, the first address.

This module deliberately imports nothing — not Home Assistant, not our API
client. It is a decision about two lists, and a decision is worth testing on
its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Ignored(str, Enum):
    """Why something announcing itself was not adopted."""

    NOT_ON_ACCOUNT = "not_on_account"
    """Announced nearby, but this account does not own it. The ordinary case in
    a block of flats, and the one that matters."""

    UNIDENTIFIABLE = "unidentifiable"
    """No usable identifier in the announcement. Malformed, or not one of ours."""

    NO_ADDRESS = "no_address"
    """Identified and owned, but gave nowhere to reach it — so there is nothing
    to adopt, even though it is genuinely the customer's."""


@dataclass(frozen=True)
class Adopted:
    """A cube the account owns AND that we can reach locally."""

    device_id: str
    address: str
    name: str
    capabilities: tuple[str, ...] = ()
    via: str = "network"
    """Where the address came from: "account" (the device list's `lan_ip`) or
    "network" (heard announcing itself). For the log line and the entity
    attribute; never for a decision — both roads passed the same gate."""


@dataclass(frozen=True)
class Reconciliation:
    """The whole answer, including what was refused and why.

    ⚠ THE REFUSALS ARE PART OF THE ANSWER, NOT A SIDE EFFECT. "Why is my cube
    not showing up" is the support question this feature will generate, and a
    reconciliation that only returned successes could not answer it.
    """

    adopted: tuple[Adopted, ...] = ()
    cloud_only: tuple[str, ...] = ()
    """Owned, but not announcing itself — normal, and not an error. Somebody
    else's job to fetch over the internet."""
    ignored: tuple[tuple[str, Ignored], ...] = field(default=())
    """(what it called itself, why).

    ⚠ THE FIRST ELEMENT IS THE RAW ANNOUNCED VALUE, NOT THE NORMALISED ONE, and
    that is deliberate. This exists to answer "why is my cube not showing up",
    and the answer is often *how it spelled itself* — an odd hostname, a
    truncated name, unexpected case. Folding that away before showing it would
    hide the very thing being diagnosed.

    ⛔ It is untrusted input. Use it in a log line; never match on it."""


def normalise_device_id(value: object) -> str | None:
    """Return a comparable device id, or None if there isn't one.

    ⛔ CASE IS THE TRAP HERE. Our identifiers are `aqm-` followed by uppercase
    hexadecimal, but announcements travel through systems that lowercase things
    without asking — hostnames especially. Comparing raw strings would silently
    fail to match a cube that is genuinely the customer's, and the symptom is
    "it just doesn't find my cube", which is indistinguishable from the network
    being wrong. Fold the case once, here, so nothing downstream has to
    remember.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned.upper()


def is_unicast_ipv4(value: object) -> bool:
    """The house line's address rule, in this integration's words: a dotted
    IPv4 with four plain octets 0-255 (no leading zeros), and a unicast one —
    not unspecified, not broadcast, not loopback, not multicast. The device's
    own `/readings` lives at such an address or nowhere."""
    if not isinstance(value, str):
        return False
    parts = value.strip().split(".")
    if len(parts) != 4:
        return False
    octets = []
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part[0] == "0") or len(part) > 3:
            return False
        n = int(part)
        if n > 255:
            return False
        octets.append(n)
    if octets == [0, 0, 0, 0] or octets == [255, 255, 255, 255]:
        return False
    if octets[0] == 127 or 224 <= octets[0] <= 239:
        return False
    return True


def account_announcements(account_devices: list[dict]) -> list[dict]:
    """The account's own addresses, shaped like announcements.

    ⭐ FIRST IN THE LIST HANDED TO `reconcile`, so the account's address wins
    over a network sighting of the same device (reconcile adopts a device once,
    first address seen). A `lan_ip` that is not a unicast IPv4 is not an
    address at all and yields nothing — the device then has only the network
    and the cloud, as before.
    """
    out: list[dict] = []
    for device in account_devices or []:
        if not isinstance(device, dict):
            continue
        address = device.get("lan_ip")
        if not is_unicast_ipv4(address):
            continue
        out.append({
            "device_id": device.get("device_id"),
            "address": address.strip(),
            "via": "account",
        })
    return out


def reconcile(
    account_devices: list[dict],
    discovered: list[dict],
) -> Reconciliation:
    """Decide which announced cubes may be adopted.

    `account_devices` is what our API returned for the signed-in account — the
    authority. `discovered` is whatever was heard on the network — untrusted —
    with the account's own addresses (`account_announcements`) ahead of it when
    the caller wants them to win, which it does.
    """
    # Index the authority first. Anything not in here cannot be adopted, no
    # matter how convincing it sounds.
    owned: dict[str, dict] = {}
    for device in account_devices or []:
        key = normalise_device_id(device.get("device_id"))
        if key is not None:
            owned[key] = device

    adopted: list[Adopted] = []
    ignored: list[tuple[str, Ignored]] = []
    seen: set[str] = set()

    for announcement in discovered or []:
        raw = announcement.get("device_id")
        key = normalise_device_id(raw)

        if key is None:
            ignored.append((str(raw), Ignored.UNIDENTIFIABLE))
            continue

        if key not in owned:
            # ⛔ THE REFUSAL THIS MODULE EXISTS FOR.
            ignored.append((str(raw), Ignored.NOT_ON_ACCOUNT))
            continue

        if key in seen:
            # A cube announcing twice (two interfaces, a re-announce arriving
            # late) is one cube. Adopting it twice would give the customer
            # duplicate entities and two sets of history for one device.
            continue

        address = announcement.get("address")
        if not isinstance(address, str) or not address.strip():
            ignored.append((str(raw), Ignored.NO_ADDRESS))
            continue

        record = owned[key]
        seen.add(key)
        via = announcement.get("via")
        adopted.append(
            Adopted(
                device_id=record.get("device_id") or key,
                address=address.strip(),
                via=via if via in ("account", "network") else "network",
                # ⚠ THE NAME COMES FROM THE ACCOUNT, NOT THE ANNOUNCEMENT.
                # What the customer called their cube lives in their account;
                # letting the network supply a display name would let anything
                # on the wifi choose what appears in their house.
                name=record.get("name") or record.get("device_id") or key,
                capabilities=tuple(record.get("capabilities") or ()),
            )
        )

    cloud_only = tuple(
        owned[key].get("device_id") or key for key in owned if key not in seen
    )

    return Reconciliation(
        adopted=tuple(adopted),
        cloud_only=cloud_only,
        ignored=tuple(ignored),
    )
