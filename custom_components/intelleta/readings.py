"""Turning a cube's payload into values Home Assistant can show. Card 88.

⛔⛔ ABSENT IS NOT ZERO, AND THIS IS THE WHOLE POINT OF THE MODULE.

The device contract is explicit: every measurement is optional, and a field is
present only if the device declares the capability AND the sensor's current
reading is valid. A failed or warming sensor OMITS its field — never null, never
zero-as-unknown.

Read carelessly, that turns into lies with a straight face:

  * a warming carbon-monoxide cell reads 0 ppm — "the air is perfectly clean"
  * a failed particulate sensor reads 0 µg/m³ — the same, in the room where it
    matters most
  * an omitted memory figure reads 0 bytes — "this cube cannot allocate
    anything at all"

None of those look like errors. They look like good news, which is the worst
shape of wrong a sensor product can produce. So absence is preserved all the way
through: a missing field becomes None, Home Assistant shows the entity as having
no value, and nobody is told the air is clean by a sensor that is not working.

⚠ AND THE VALUES ARE RANGE-CHECKED. The contract publishes bounds; a reading
outside them is a malfunction or a corrupted payload, not a measurement, and
passing it on would record an impossible number into history that cannot be
removed afterwards.

No Home Assistant imports — this is parsing, and parsing is worth testing on its
own.
"""

from __future__ import annotations

from dataclasses import dataclass

# Bounds straight from the device contract's telemetry schema. A value outside
# these is not a reading.
#
# ⚠ INCLUSIVE, AND THE EDGES ARE REAL VALUES. Zero particulates is a genuine
# reading from a clean room; refusing it as "suspiciously perfect" would drop
# good data. What zero must never mean is "the field was missing", and that
# distinction is made by presence, not by value.
_BOUNDS: dict[str, tuple[float, float]] = {
    "pm1": (0, 100000),
    "pm2_5": (0, 100000),
    "pm10": (0, 100000),
    "co2": (0, 40000),
    "voc_index": (1, 500),
    "nox_index": (1, 500),
    "co_ppm": (0, 100000),
    "temp": (-40, 85),
    "rh": (0, 100),
    "lux": (0, 1000000),
}

_META_BOUNDS: dict[str, tuple[float, float]] = {
    # Signal strength is negative decibels; a positive one is a parsing error
    # somewhere upstream, not a very strong signal.
    "rssi": (-200, 0),
    "heap": (0, 1 << 30),
    "heap_largest": (0, 1 << 30),
}

_VOICE_STATES = frozenset({"idle", "listening", "thinking", "responding", "disabled"})

# The contract's own floor: devices must not publish before their clock is set,
# so anything earlier is a cube that ignored that or a corrupted payload.
_TIMESTAMP_FLOOR = 1700000000


@dataclass(frozen=True)
class Readings:
    """One payload, parsed. Every value may be None, and None means unknown."""

    device_id: str | None = None
    timestamp: int | None = None
    values: dict[str, float | str] | None = None
    """⚠ ONLY KEYS THAT WERE ACTUALLY PRESENT AND VALID. A caller asking for a
    key that is not here gets None, which is what the entity shows. There is
    deliberately no default-to-zero anywhere."""

    @property
    def usable(self) -> bool:
        """A payload with no trustworthy timestamp cannot be placed in time, so
        it cannot be compared against what is already showing (card 95) and is
        not usable — regardless of how good the numbers look."""
        return self.device_id is not None and self.timestamp is not None

    def get(self, key: str) -> float | str | None:
        return (self.values or {}).get(key)


def _number(raw: object, bounds: tuple[float, float]) -> float | None:
    """A number inside its contract bounds, or None. Never a substitute value."""
    # ⛔ BOOLEANS ARE NOT NUMBERS, even though Python says they are. `True` would
    # sail through as 1 and be recorded as a measurement.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    low, high = bounds
    if value < low or value > high:
        return None
    return value


def parse(payload: object) -> Readings:
    """Parse one telemetry payload. Never raises; bad input yields unknowns."""
    if not isinstance(payload, dict):
        return Readings()

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        device_id = None

    timestamp = payload.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        timestamp = None
    elif timestamp < _TIMESTAMP_FLOOR:
        timestamp = None

    values: dict[str, float | str] = {}

    measurements = payload.get("measurements")
    if isinstance(measurements, dict):
        for key, bounds in _BOUNDS.items():
            # ⛔ MISSING KEYS ARE SKIPPED, NOT DEFAULTED. This one line is the
            # difference between "we don't know" and "the air is clean".
            if key not in measurements:
                continue
            value = _number(measurements[key], bounds)
            if value is not None:
                values[key] = value

    meta = payload.get("meta")
    if isinstance(meta, dict):
        for key, bounds in _META_BOUNDS.items():
            if key not in meta:
                # ⭐ `heap_largest` in particular: added to the contract
                # 2026-08-26, so every cube in the field today omits it. Absent
                # must read as unknown — zero would say "this cube cannot
                # allocate anything at all", which is alarming and wrong.
                continue
            value = _number(meta[key], bounds)
            if value is not None:
                values[key] = value

        firmware = meta.get("fw")
        if isinstance(firmware, str) and firmware.strip():
            values["fw"] = firmware.strip()

    # ⚠ A CLOSED VOCABULARY, NOT ANY STRING. An unexpected word would be
    # recorded as a new enum value and then shown to the customer verbatim.
    voice_state = payload.get("voice_state")
    if isinstance(voice_state, str) and voice_state in _VOICE_STATES:
        values["voice_state"] = voice_state

    return Readings(device_id=device_id, timestamp=timestamp, values=values or None)
