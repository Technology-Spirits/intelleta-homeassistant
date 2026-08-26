"""Card 88 — only create what the device declares, and label it correctly.

Two rules, both cheap to break and expensive to have broken:

  ⛔ An entity for a part that is not fitted shows the customer a sensor that
     never updates. "Unavailable" forever reads as broken hardware rather than
     as absent hardware.

  ⛔ Sensor types decide which of Home Assistant's own features apply. History
     recorded under the wrong type CANNOT be reinterpreted afterwards — the
     customer has to throw it away. So they are pinned, not trusted.
"""

from __future__ import annotations

from conftest import load

caps = load("capabilities")
sensors_for = caps.sensors_for
known_capabilities = caps.known_capabilities

FULL_CUBE = ["pm", "co2", "voc", "nox", "co", "temp", "rh", "lux", "panel", "voice"]


def keys(capabilities):
    return {s.key for s in sensors_for(capabilities)}


def spec(capabilities, key):
    return next(s for s in sensors_for(capabilities) if s.key == key)


# ── declare-or-it-does-not-exist ────────────────────────────────────────────


def test_a_full_cube_gets_every_air_reading():
    assert {
        "pm1", "pm2_5", "pm10", "co2", "voc_index", "nox_index",
        "co_ppm", "temp", "rh", "lux",
    } <= keys(FULL_CUBE)


def test_a_single_gas_cube_gets_only_its_own_gas():
    """⛔ THE RULE THAT LETS ONE INTEGRATION SERVE THE WHOLE RANGE. A CO2-only
    cube must not sprout particulate sensors that will never read."""
    got = keys(["co2", "temp", "rh"])

    assert "co2" in got
    for absent in ("pm1", "pm2_5", "pm10", "co_ppm", "voc_index", "nox_index", "lux"):
        assert absent not in got, f"{absent} was invented for a cube that never claimed it"


def test_a_screenless_cube_gets_no_screen_sensors_and_that_is_fine():
    """`panel` declares a screen, not a reading. It gates controls (card 97)."""
    with_screen = keys(["co2", "panel"])
    without = keys(["co2"])
    assert with_screen == without


def test_a_voiceless_cube_has_no_voice_state():
    assert "voice_state" in keys(["co2", "voice"])
    assert "voice_state" not in keys(["co2"])


def test_a_cube_declaring_nothing_still_gets_its_diagnostics():
    """A cube with no sensors at all is still a device that can be online,
    offline, and running a firmware version."""
    got = keys([])
    assert "rssi" in got
    assert "pm2_5" not in got


def test_an_unknown_capability_is_ignored_rather_than_breaking_the_integration():
    """⚠ The contract says capability keys are ADDITIVE and consumers must
    ignore ones they do not know. A cube shipped after this integration was
    released must not break the customer's Home Assistant."""
    got = keys(["co2", "something_invented_next_year"])
    assert "co2" in got


def test_capabilities_that_overlap_do_not_produce_duplicates():
    """Two entities for one reading would split its history in half."""
    specs = sensors_for(["temp", "rh", "temp"])
    assert len([s for s in specs if s.key == "temp"]) == 1


# ── the labelling that Home Assistant acts on ───────────────────────────────


def test_each_air_reading_carries_the_type_home_assistant_expects():
    """These strings are Home Assistant's published vocabulary. If one is wrong
    the entity quietly loses its special treatment — the air-quality card, unit
    conversion, statistics — rather than failing loudly. Hence pinning."""
    expected = {
        "pm1": ("pm1", "µg/m³"),
        "pm2_5": ("pm25", "µg/m³"),
        "pm10": ("pm10", "µg/m³"),
        "co2": ("carbon_dioxide", "ppm"),
        "co_ppm": ("carbon_monoxide", "ppm"),
        "temp": ("temperature", "°C"),
        "rh": ("humidity", "%"),
        "lux": ("illuminance", "lx"),
    }
    for key, (device_class, unit) in expected.items():
        s = spec(FULL_CUBE, key)
        assert s.device_class == device_class, f"{key} would lose its Home Assistant treatment"
        assert s.unit == unit


def test_the_two_indices_have_no_unit_and_no_class_on_purpose():
    """⛔ NOT A CONCENTRATION. They are a manufacturer's algorithm output on a
    1–500 scale. Home Assistant's volatile-organic-compound classes mean real
    measured concentrations; claiming one would invite unit conversions that
    produce confident nonsense. A plain number, correctly labelled, is honest.
    """
    for key in ("voc_index", "nox_index"):
        s = spec(FULL_CUBE, key)
        assert s.device_class is None, f"{key} must not claim to be a concentration"
        assert s.unit is None
        assert s.state_class == "measurement", "it is still a number worth graphing"


def test_voice_state_is_an_enum_and_records_no_statistics():
    """⚠ A string with a measurement state class makes Home Assistant try to
    compute statistics for it and complain every few minutes."""
    s = spec(FULL_CUBE, "voice_state")
    assert s.device_class == "enum"
    assert s.state_class is None
    assert s.unit is None


def test_the_air_readings_are_not_buried_as_diagnostics():
    """The customer came for these. Anything marked diagnostic is tucked away by
    Home Assistant rather than shown beside the air readings."""
    for key in ("pm2_5", "co2", "temp", "rh", "voc_index"):
        assert spec(FULL_CUBE, key).category is None


def test_the_housekeeping_numbers_are_marked_diagnostic():
    for key in ("rssi", "heap", "heap_largest", "voice_state"):
        assert spec(FULL_CUBE, key).category == "diagnostic"


def test_diagnostics_arrive_whatever_the_cube_is_made_of():
    """They ride `meta`, not `measurements`, so they are not capability-gated."""
    for declaration in ([], ["co2"], FULL_CUBE):
        assert {"rssi", "heap", "heap_largest"} <= keys(declaration)


def test_the_largest_free_block_is_present_because_the_free_total_cannot_answer():
    """⭐ Added to the device contract 2026-08-26. The free total cannot say
    whether an allocation will succeed — measured on a real cube: 9,788 bytes
    free with no block larger than 2,972.

    ⛔ Older cubes omit it, and absent must read as UNKNOWN. Zero would say
    "this cube cannot allocate anything at all", which is alarming and wrong —
    that rule belongs to whatever reads the payload, and this test exists so the
    sensor is not quietly dropped in the meantime.
    """
    s = spec(FULL_CUBE, "heap_largest")
    assert s.unit == "B"
    assert s.category == "diagnostic"


def test_every_name_is_placeholder_english_kept_in_one_place():
    """⚠ Customer-visible strings go through Raye and Thomas. Keeping them all
    in one table makes that a find-and-replace rather than archaeology."""
    for s in sensors_for(FULL_CUBE):
        assert s.name and s.name.strip() == s.name
        assert not s.name.endswith(" ")


def test_the_known_capability_set_matches_the_device_contract():
    """A cube declaring something outside this set is half-supported, and being
    able to SEE that is the point of exposing it."""
    assert known_capabilities() == {
        "pm", "co2", "voc", "nox", "co", "temp", "rh", "lux",
        "panel", "numeric_display", "voice",
    }
