"""What a declared capability entitles a cube to show. Card 88.

⛔ CREATE ONLY WHAT THE DEVICE DECLARES.

A cube says what it has when it connects. An entity for a part that is not
fitted is a defect, not a harmless extra: it shows the customer a sensor that
never updates, and "unavailable" forever reads as broken hardware rather than as
absent hardware. This is also the rule that lets ONE integration serve the LCD
wedge, the glowing cubes and the single-gas cubes without a rewrite — so a
shortcut here is a rewrite later.

⛔ THE SENSOR TYPES ARE NOT COSMETIC, AND GETTING THEM WRONG IS EXPENSIVE LATER.
Home Assistant uses the type to decide which of its own features apply — the
air-quality card, long-term statistics, unit conversion for people who prefer
Fahrenheit. History recorded under the wrong type **cannot be reinterpreted
afterwards**; the customer has to throw it away. So these are set once, from the
device contract, and pinned by tests.

⚠ NO HOME ASSISTANT IMPORTS HERE, deliberately. This is a table of facts about
our own device, so it stays testable in a second without installing anything.
The thin adapter that turns these into Home Assistant entity descriptions lives
with the entities.
"""

from __future__ import annotations

from dataclasses import dataclass

# Home Assistant's own vocabulary, as plain strings so this module needs nothing
# installed. ⚠ These are its published names — if one is ever wrong the entity
# quietly loses its special treatment rather than failing loudly, which is why
# there is a test asserting each one rather than trust.
DEVICE_CLASS_PM1 = "pm1"
DEVICE_CLASS_PM25 = "pm25"
DEVICE_CLASS_PM10 = "pm10"
DEVICE_CLASS_CO2 = "carbon_dioxide"
DEVICE_CLASS_CO = "carbon_monoxide"
DEVICE_CLASS_TEMPERATURE = "temperature"
DEVICE_CLASS_HUMIDITY = "humidity"
DEVICE_CLASS_ILLUMINANCE = "illuminance"
DEVICE_CLASS_SIGNAL_STRENGTH = "signal_strength"
DEVICE_CLASS_DATA_SIZE = "data_size"
DEVICE_CLASS_ENUM = "enum"

STATE_CLASS_MEASUREMENT = "measurement"

CATEGORY_DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class SensorSpec:
    """One reading the cube can show, and how Home Assistant should treat it."""

    key: str
    """Where to find it in the payload — the contract's own field name."""

    name: str
    """⚠ PLACEHOLDER ENGLISH. Every customer-visible string goes through Raye and
    Thomas. Keeping them all in this one table is what makes that a find-and-
    replace rather than an archaeology exercise."""

    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = STATE_CLASS_MEASUREMENT
    category: str | None = None
    """None is an ordinary sensor the customer cares about; diagnostic ones are
    tucked away by Home Assistant rather than shown beside the air readings."""


# ── What each capability implies ────────────────────────────────────────────
#
# Straight from the device contract's capability registry. ⛔ A capability
# absent from a cube's declaration means NONE of its sensors exist on that cube.

_BY_CAPABILITY: dict[str, tuple[SensorSpec, ...]] = {
    "pm": (
        SensorSpec("pm1", "PM1", DEVICE_CLASS_PM1, "µg/m³"),
        SensorSpec("pm2_5", "PM2.5", DEVICE_CLASS_PM25, "µg/m³"),
        SensorSpec("pm10", "PM10", DEVICE_CLASS_PM10, "µg/m³"),
    ),
    "co2": (
        SensorSpec("co2", "Carbon dioxide", DEVICE_CLASS_CO2, "ppm"),
    ),
    "co": (
        SensorSpec("co_ppm", "Carbon monoxide", DEVICE_CLASS_CO, "ppm"),
    ),
    "temp": (
        SensorSpec("temp", "Temperature", DEVICE_CLASS_TEMPERATURE, "°C"),
    ),
    "rh": (
        SensorSpec("rh", "Humidity", DEVICE_CLASS_HUMIDITY, "%"),
    ),
    "lux": (
        SensorSpec("lux", "Illuminance", DEVICE_CLASS_ILLUMINANCE, "lx"),
    ),
    # ⛔ THE TWO INDICES HAVE NO DEVICE CLASS AND NO UNIT, AND THAT IS CORRECT.
    # They are the output of a manufacturer's algorithm on a 1–500 scale — not a
    # concentration, not parts per billion, not convertible to anything. Home
    # Assistant does have volatile-organic-compound classes, but they mean real
    # measured concentrations; claiming one here would invite conversions that
    # produce confident nonsense. A plain number, correctly labelled, is honest.
    "voc": (
        SensorSpec("voc_index", "VOC index", None, None),
    ),
    "nox": (
        SensorSpec("nox_index", "NOx index", None, None),
    ),
    "voice": (
        # ⚠ Not a measurement — an enum. state_class must be None or Home
        # Assistant tries to record statistics for a string and logs about it
        # every few minutes.
        SensorSpec(
            "voice_state",
            "Voice",
            DEVICE_CLASS_ENUM,
            None,
            state_class=None,
            category=CATEGORY_DIAGNOSTIC,
        ),
    ),
    # `panel` and `numeric_display` declare a screen, not a reading. They gate
    # CONTROLS (card 97), and deliberately imply no sensor at all.
    "panel": (),
    "numeric_display": (),
}

# ── Diagnostics every cube reports, whatever it is made of ──────────────────
#
# These ride `meta` rather than `measurements`, so they are not capability-gated
# — but they ARE diagnostics: useful when something is wrong, clutter beside the
# air readings otherwise.
_DIAGNOSTICS: tuple[SensorSpec, ...] = (
    SensorSpec(
        "rssi", "Signal strength", DEVICE_CLASS_SIGNAL_STRENGTH, "dBm",
        category=CATEGORY_DIAGNOSTIC,
    ),
    SensorSpec(
        "heap", "Free memory", DEVICE_CLASS_DATA_SIZE, "B",
        category=CATEGORY_DIAGNOSTIC,
    ),
    # ⭐ NEW, AND OLDER CUBES OMIT IT. Added to the device contract 2026-08-26
    # because the free total cannot say whether an allocation will succeed —
    # measured on a real cube: 9,788 bytes free with no block larger than 2,972.
    # ⛔ Absent means UNKNOWN, never zero: zero would read as "this cube cannot
    # allocate anything at all", which is alarming and wrong.
    SensorSpec(
        "heap_largest", "Largest free block", DEVICE_CLASS_DATA_SIZE, "B",
        category=CATEGORY_DIAGNOSTIC,
    ),
)


def sensors_for(capabilities: object) -> tuple[SensorSpec, ...]:
    """The sensors a cube declaring `capabilities` should have. Nothing more.

    Unknown capabilities are ignored rather than refused: the contract says
    capability keys are additive and consumers must ignore ones they do not
    know. A cube shipped after this integration was released must not break it.
    """
    if not capabilities:
        return _DIAGNOSTICS

    specs: list[SensorSpec] = []
    seen: set[str] = set()
    for capability in capabilities:
        for spec in _BY_CAPABILITY.get(capability, ()):
            if spec.key not in seen:
                seen.add(spec.key)
                specs.append(spec)

    return tuple(specs) + _DIAGNOSTICS


def known_capabilities() -> frozenset[str]:
    """Every capability this integration understands. For diagnostics — so a
    cube declaring something new is visible rather than silently half-supported.
    """
    return frozenset(_BY_CAPABILITY)
