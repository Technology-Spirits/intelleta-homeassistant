"""Hearing cubes announce themselves, and deciding which to believe. Card 93.

This is the wiring. The DECISION — which announced cube may be adopted — lives in
matching.py, is free of every import, and is tested on its own. Nothing in this
file may decide anything; it listens, hands what it heard to that decision, and
records the answer.

⛔ THE ACCOUNT LIST IS THE AUTHORITY. Everything arriving here came off the local
network and is untrusted: a flat-mate's cube, a neighbour's through a thin wall,
or something merely claiming to be one. What it says about itself is a pointer,
never a permission.

⚠ AND IT IS BEST-EFFORT, ALWAYS. If discovery fails, or the customer's network
blocks it, every cube simply stays on the cloud path. A house where announcement
does not work must still be a house where the product works.
"""

from __future__ import annotations

import logging

from homeassistant.components import zeroconf
from homeassistant.core import HomeAssistant

from .matching import Ignored, reconcile

_LOGGER = logging.getLogger(__name__)

# ⛔ THIS STRING IS A CONTRACT WITH THE FIRMWARE. The cube advertises
# `_intelleta._tcp` (aqm 527); changing either side alone makes every installed
# integration stop finding cubes — silently, with no error anywhere, because
# "heard nothing" and "heard nothing we recognise" look identical from here.
SERVICE_TYPE = "_intelleta._tcp.local."


async def async_discover(hass: HomeAssistant, timeout_s: float = 3.0) -> list[dict]:
    """Everything announcing itself as one of ours, right now.

    Returns plain dicts — `{"device_id": ..., "address": ...}` — because that is
    what `matching.reconcile` takes, and it takes plain dicts so it can stay
    free of Home Assistant entirely.
    """
    try:
        aiozc = await zeroconf.async_get_async_instance(hass)
        infos = await _async_gather(aiozc, timeout_s)
    except Exception as err:  # noqa: BLE001
        # ⚠ BROAD AND SWALLOWED, DELIBERATELY. Discovery is a convenience for
        # FINDING a cube, never a dependency of one. A failure here must cost
        # the local path and nothing else.
        _LOGGER.debug("discovery unavailable: %s", err)
        return []

    found: list[dict] = []
    for info in infos:
        device_id = _device_id_of(info)
        address = _address_of(info)
        if device_id is None and address is None:
            continue
        found.append({"device_id": device_id, "address": address})
    return found


async def _async_gather(aiozc, timeout_s: float) -> list:
    """Ask the network and collect what answers."""
    from zeroconf import ServiceBrowser  # noqa: PLC0415
    from zeroconf.asyncio import AsyncServiceInfo  # noqa: PLC0415

    names: list[str] = []

    class _Collector:
        def add_service(self, zc, type_, name):  # noqa: ANN001, ARG002
            names.append(name)

        def update_service(self, zc, type_, name):  # noqa: ANN001, ARG002
            pass

        def remove_service(self, zc, type_, name):  # noqa: ANN001, ARG002
            # ⚠ A cube that has gone is simply absent from the next sweep. It is
            # not removed from the integration here — reconcile decides that,
            # once, from the whole picture.
            pass

    import asyncio  # noqa: PLC0415

    browser = ServiceBrowser(aiozc.zeroconf, SERVICE_TYPE, _Collector())
    try:
        await asyncio.sleep(timeout_s)
    finally:
        browser.cancel()

    infos = []
    for name in names:
        info = AsyncServiceInfo(SERVICE_TYPE, name)
        if await info.async_request(aiozc.zeroconf, int(timeout_s * 1000)):
            infos.append(info)
    return infos


def _device_id_of(info) -> str | None:
    """The identifier, from the text record or failing that the instance name.

    ⚠ TWO PLACES BECAUSE THE FIRMWARE PUTS IT IN BOTH, and a name arrives having
    passed through systems that lowercase and truncate. Normalising and matching
    is matching.py's job; this only fetches.
    """
    try:
        raw = (info.properties or {}).get(b"id")
        if isinstance(raw, bytes):
            return raw.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        pass

    name = getattr(info, "name", "") or ""
    return name.split(".")[0] or None


def _address_of(info) -> str | None:
    """A reachable address, or None.

    ⚠ THE FIRST IPv4 ADDRESS. A cube on several interfaces announces several;
    any of them reaches it, and reconcile adopts a cube once regardless of how
    many times it was heard.
    """
    try:
        for addr in info.parsed_addresses():
            if ":" not in addr:  # skip IPv6 — the cube serves on IPv4
                return addr
    except Exception:  # noqa: BLE001
        pass
    return None


def apply_to(coordinator, account_devices: list[dict], discovered: list[dict]) -> None:
    """Record which cubes may be reached locally, and say why the rest may not.

    ⛔ THE RESULT REPLACES THE PREVIOUS ADDRESSES RATHER THAN MERGING WITH THEM.
    A cube that has moved, been switched off, or been removed from the account
    must stop being reached at its old address — merging would leave the
    integration talking to an address nobody owns any more, which on a home
    network is a different device's address soon enough.
    """
    result = reconcile(account_devices, discovered)

    coordinator.addresses = {a.device_id: a.address for a in result.adopted}

    if result.ignored:
        # ⚠ AT DEBUG, NOT AS A WARNING. In a block of flats, hearing somebody
        # else's cube is the ORDINARY case, not a fault — warning about it would
        # train people to ignore the log.
        for announced, why in result.ignored:
            if why is Ignored.NOT_ON_ACCOUNT:
                _LOGGER.debug("ignoring %s — not on this account", announced)
            else:
                _LOGGER.debug("ignoring %s — %s", announced, why.value)

    _LOGGER.debug(
        "discovery: %d adopted, %d cloud-only, %d ignored",
        len(result.adopted), len(result.cloud_only), len(result.ignored),
    )
