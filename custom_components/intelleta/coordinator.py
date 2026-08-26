"""Keeping each cube's readings current. Card 88.

One coordinator per account. It asks the cloud which cubes exist, then asks each
cube for its readings — locally where it can, through the cloud where it cannot.

⛔ THE POLICY LIVES IN source_policy.py, NOT HERE. Which source to use, when to
give up on the local one, and whether an arriving reading may replace what is
already showing are decisions with real subtlety — a naive version makes the
customer's numbers flicker between two sources — so they are pure functions with
their own tests. This file does the plumbing and calls them.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthFailed, CloudClient, CloudUnavailable, LocalClient
from .const import API_BASE_URL, DEFAULT_CLOUD_POLL_SECONDS
from .discovery import apply_to, async_discover
from .readings import Readings, parse
from .source_policy import (
    SourceState,
    accept_reading,
    on_local_failure,
    on_local_success,
    should_try_local,
)

_LOGGER = logging.getLogger(__name__)

# Which stored column carries which contract field. Our rows are flat; the
# parser speaks the device contract's nested shape.
_MEASUREMENT_COLUMNS = (
    ("air_pm25", "pm2_5"),
    ("air_co2", "co2"),
    ("air_temp", "temp"),
    ("air_humidity", "rh"),
    ("aqm_pm1", "pm1"),
    ("aqm_pm10", "pm10"),
    ("aqm_voc_index", "voc_index"),
    ("aqm_nox_index", "nox_index"),
    ("aqm_co_ppm", "co_ppm"),
    ("aqm_lux", "lux"),
)
_META_COLUMNS = (
    ("meta_fw", "fw"),
    ("meta_rssi", "rssi"),
    ("meta_heap", "heap"),
    ("meta_heap_largest", "heap_largest"),
)


class IntellettaCoordinator(DataUpdateCoordinator):
    """Holds every cube on one account, and the freshest reading for each."""

    def __init__(self, hass: HomeAssistant, key: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="intelleta",
            update_interval=timedelta(seconds=DEFAULT_CLOUD_POLL_SECONDS),
        )
        self._session = async_get_clientsession(hass)
        self._key = key
        self._cloud = CloudClient(self._session, API_BASE_URL, key)

        self.devices: dict = {}
        """device_id -> CloudDevice, as the ACCOUNT describes it. The authority
        for what exists and what each cube can do (card 93)."""

        self.addresses: dict[str, str] = {}
        """device_id -> local address, for cubes heard announcing themselves AND
        owned by this account.

        ⛔ WRITTEN ONLY BY discovery.apply_to, which asks matching.reconcile.
        Nothing else may put an address in here: the whole security boundary of
        the local path is that an address is trusted because the ACCOUNT lists
        the cube, never because the network offered one.

        ⚠ Empty on a network where announcement does not work, and that is fine
        — every cube falls back to the cloud path."""

        self._sources: dict[str, SourceState] = {}

    def source_state(self, device_id: str) -> SourceState:
        return self._sources.setdefault(device_id, SourceState())

    async def _async_update_data(self) -> dict:
        try:
            devices = await self._cloud.async_list_devices()
        except AuthFailed as err:
            # ⛔ RAISED AS AN AUTH FAILURE, NOT SWALLOWED. Home Assistant turns
            # this into the "please re-authenticate" prompt. Treating a revoked
            # key as a transient outage is exactly what produces "it just
            # stopped working" with nothing on screen to explain it.
            raise ConfigEntryAuthFailed(str(err)) from err
        except CloudUnavailable as err:
            raise UpdateFailed(str(err)) from err

        self.devices = {device.device_id: device for device in devices}

        # ── Who is on the network, and which of them are ours (card 93) ──
        #
        # ⚠ EVERY CYCLE RATHER THAN ONCE AT SETUP. Cubes move, get switched off,
        # change address, and are added to the account after the integration was
        # installed. A one-shot sweep at startup would leave the local path
        # frozen at whatever happened to be true that minute.
        #
        # ⛔ THE ACCOUNT LIST IS PASSED IN AS THE AUTHORITY. What answered on the
        # network is untrusted input; reconcile decides, not this loop.
        await self._async_refresh_addresses()

        results: dict = dict(self.data or {})
        now = self.hass.loop.time()

        for device_id in self.devices:
            fresh = await self._read_one(device_id, now)
            if fresh is None or not fresh.usable:
                continue

            current = results.get(device_id)
            # ⛔ THE TIMESTAMP DECIDES, NEVER THE ARRIVAL ORDER (card 95). This
            # is what stops a cloud copy of an older moment landing on top of a
            # fresher local reading and making the numbers jump backwards.
            if accept_reading(
                current.timestamp if current else None,
                fresh.timestamp,
                self.source_state(device_id).active,
            ):
                results[device_id] = fresh

        # A cube removed from the account stops being shown, rather than
        # lingering with its last reading for ever.
        return {k: v for k, v in results.items() if k in self.devices}

    async def _async_refresh_addresses(self) -> None:
        """Ask the network who is there, and keep the ones this account owns.

        ⚠ BEST EFFORT, ALWAYS. If discovery fails or the network blocks it,
        every cube simply stays on the cloud path — a house where announcement
        does not work must still be a house where the product works.
        """
        try:
            discovered = await async_discover(self.hass)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("discovery sweep failed: %s", err)
            return

        apply_to(
            self,
            [device.as_dict() for device in self.devices.values()],
            discovered,
        )

    async def _read_one(self, device_id: str, now: float) -> Readings | None:
        state = self.source_state(device_id)
        address = self.addresses.get(device_id)

        if address and should_try_local(state, now):
            payload = await LocalClient(self._session, address).async_readings()
            if payload is not None:
                self._sources[device_id] = on_local_success(state)
                return parse(payload)
            # ⚠ ONE MISS IS NOT AN OUTAGE. The policy decides whether this is
            # enough to fall back, and usually it is not.
            self._sources[device_id] = on_local_failure(state, now)

        return await self._read_from_cloud(device_id)

    async def _read_from_cloud(self, device_id: str) -> Readings | None:
        try:
            async with self._session.get(
                f"{API_BASE_URL}/integration/devices/{device_id}/latest",
                headers={"Authorization": f"Bearer {self._key}"},
            ) as response:
                if response.status != 200:
                    return None
                return parse(to_contract_shape(await response.json()))
        except Exception as err:  # noqa: BLE001
            # ⚠ BROAD, AND ONLY HERE. One cube's reading failing must never take
            # down the whole account's update — the other cubes in the house are
            # fine and should keep working.
            _LOGGER.debug("cloud reading for %s failed: %s", device_id, err)
            return None


def to_contract_shape(row: object) -> dict:
    """Flat stored row -> the nested shape the parser speaks.

    ⚠ TRANSLATED HERE RATHER THAN TEACHING THE PARSER TWO SHAPES. The parser is
    the thing that knows "absent is not zero"; giving it two input formats would
    be two places for that rule to be got wrong.
    """
    if not isinstance(row, dict):
        return {}

    measurements = {}
    for stored, contract in _MEASUREMENT_COLUMNS:
        # ⛔ ABSENT STAYS ABSENT. Copying a missing key across as None would give
        # the parser a present-but-null field, which the contract never sends
        # and which would then have to be special-cased there instead.
        if stored in row:
            measurements[contract] = row[stored]

    meta = {}
    for stored, contract in _META_COLUMNS:
        if stored in row:
            meta[contract] = row[stored]

    shaped = {
        "device_id": row.get("device_id"),
        "timestamp": row.get("timestamp"),
        "measurements": measurements,
        "meta": meta,
    }
    if "aqm_voice_state" in row:
        shaped["voice_state"] = row["aqm_voice_state"]
    return shaped
