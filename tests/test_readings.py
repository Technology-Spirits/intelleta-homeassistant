"""Card 88 — absent is not zero.

⛔⛔ THE DEFECT THIS PREVENTS LOOKS LIKE GOOD NEWS.

The device contract says a failed or warming sensor OMITS its field. Read
carelessly, that becomes:

  * a warming carbon-monoxide cell reading 0 ppm — "the air is perfectly clean"
  * a failed particulate sensor reading 0 µg/m³ — the same, in the room where it
    matters most

Neither looks like an error. That is the worst shape of wrong a sensor product
can produce, and it is one careless `.get(key, 0)` away at all times.
"""

from __future__ import annotations

from conftest import load

readings = load("readings")
parse = readings.parse

GOOD_TS = 1787725998
DEVICE = "aqm-CCBA97047AFC"


def payload(measurements=None, meta=None, **extra):
    body = {"device_id": DEVICE, "timestamp": GOOD_TS, "schema_version": 1}
    if measurements is not None:
        body["measurements"] = measurements
    if meta is not None:
        body["meta"] = meta
    body.update(extra)
    return body


# ── the rule ────────────────────────────────────────────────────────────────


def test_a_missing_measurement_is_unknown_and_never_zero():
    """⛔ THE ONE THAT MATTERS. A cube reporting only CO2 must not be read as
    reporting zero of everything else."""
    r = parse(payload({"co2": 549}))

    assert r.get("co2") == 549
    for absent in ("pm2_5", "co_ppm", "voc_index", "temp", "rh"):
        assert r.get(absent) is None, f"{absent} was invented as a value"


def test_a_warming_co_cell_does_not_report_clean_air():
    """The exact scenario: the cell omits its field while warming. Anything that
    turns that into 0 ppm tells the customer the air is safe."""
    r = parse(payload({"co2": 600, "pm2_5": 12}))

    assert r.get("co_ppm") is None
    assert r.get("co_ppm") != 0


def test_no_measurements_block_at_all_is_all_unknown():
    r = parse(payload())
    assert r.get("co2") is None
    assert r.usable, "a cube with no valid readings yet is still a cube"


def test_a_genuine_zero_is_kept_because_zero_is_a_real_reading():
    """⚠ THE OTHER HALF OF THE RULE. A clean room genuinely reads zero
    particulates; refusing it as suspicious would drop good data. What zero must
    never mean is 'the field was missing' — and that is decided by presence, not
    by value."""
    r = parse(payload({"pm2_5": 0, "pm1": 0.0}))

    assert r.get("pm2_5") == 0
    assert r.get("pm1") == 0


# ── values that are not measurements ────────────────────────────────────────


def test_a_value_outside_its_contract_bounds_is_refused():
    """A malfunction or a corrupted payload, not a measurement. Passing it on
    would write an impossible number into history that cannot be removed."""
    assert parse(payload({"co2": 99999})).get("co2") is None      # ceiling 40000
    assert parse(payload({"temp": -300})).get("temp") is None     # floor -40
    assert parse(payload({"rh": 150})).get("rh") is None          # ceiling 100
    assert parse(payload({"voc_index": 0})).get("voc_index") is None   # floor 1
    assert parse(payload({"nox_index": 501})).get("nox_index") is None # ceiling 500


def test_the_bounds_are_inclusive_at_both_ends():
    assert parse(payload({"voc_index": 1})).get("voc_index") == 1
    assert parse(payload({"voc_index": 500})).get("voc_index") == 500
    assert parse(payload({"rh": 100})).get("rh") == 100
    assert parse(payload({"temp": -40})).get("temp") == -40


def test_things_that_are_not_numbers_are_refused():
    for junk in ("500", None, [], {}, float("nan"), float("inf")):
        assert parse(payload({"co2": junk})).get("co2") is None, f"{junk!r} passed as a reading"


def test_a_boolean_is_not_a_measurement_even_though_python_thinks_so():
    """⛔ `True` would sail through as 1 and be recorded as a reading."""
    assert parse(payload({"co2": True})).get("co2") is None
    assert parse(payload({"pm2_5": False})).get("pm2_5") is None


def test_one_bad_value_does_not_discard_the_good_ones_beside_it():
    r = parse(payload({"co2": 549, "temp": 999, "rh": 41.5}))

    assert r.get("co2") == 549
    assert r.get("rh") == 41.5
    assert r.get("temp") is None


# ── timestamps ──────────────────────────────────────────────────────────────


def test_a_payload_with_no_usable_timestamp_is_not_usable():
    """⛔ It cannot be placed in time, so it cannot be compared against what is
    already showing (card 95). Good-looking numbers do not rescue it."""
    assert not parse({"device_id": DEVICE, "measurements": {"co2": 549}}).usable
    assert not parse(payload(timestamp="yesterday")).usable
    assert not parse(payload(timestamp=True)).usable


def test_a_timestamp_below_the_contract_floor_is_refused():
    """The contract forbids publishing before the clock is set, so anything
    earlier is a cube that ignored that, or a corrupted payload."""
    assert not parse(payload(timestamp=12345)).usable


def test_a_payload_with_no_device_is_not_usable():
    body = payload({"co2": 549})
    del body["device_id"]
    assert not parse(body).usable


# ── meta and diagnostics ────────────────────────────────────────────────────


def test_the_diagnostics_come_through_when_present():
    r = parse(payload({"co2": 549}, meta={"fw": "1.2.3", "rssi": -30, "heap": 75427}))

    assert r.get("fw") == "1.2.3"
    assert r.get("rssi") == -30
    assert r.get("heap") == 75427


def test_the_largest_free_block_is_unknown_on_every_cube_in_the_field_today():
    """⭐ Added to the contract 2026-08-26, so older cubes omit it entirely.

    ⛔ Absent must read as unknown. Zero would say "this cube cannot allocate
    anything at all" — alarming, and wrong.
    """
    older = parse(payload({"co2": 549}, meta={"fw": "1.2.3", "heap": 75427}))
    assert older.get("heap_largest") is None

    newer = parse(payload({"co2": 549}, meta={"fw": "1.2.3", "heap": 75427, "heap_largest": 21504}))
    assert newer.get("heap_largest") == 21504


def test_a_positive_signal_strength_is_a_parsing_error_not_a_strong_signal():
    assert parse(payload(meta={"rssi": 30})).get("rssi") is None
    assert parse(payload(meta={"rssi": -30})).get("rssi") == -30


def test_an_empty_firmware_string_is_not_a_firmware_version():
    assert parse(payload(meta={"fw": "  "})).get("fw") is None
    assert parse(payload(meta={"fw": " 1.2.3 "})).get("fw") == "1.2.3"


# ── voice state ─────────────────────────────────────────────────────────────


def test_voice_state_comes_through_when_it_is_one_of_the_known_words():
    for state in ("idle", "listening", "thinking", "responding", "disabled"):
        assert parse(payload(voice_state=state)).get("voice_state") == state


def test_an_unexpected_voice_word_is_refused_rather_than_shown_verbatim():
    """⚠ A CLOSED VOCABULARY. An unknown word would be recorded as a new enum
    value and then displayed to the customer exactly as received."""
    assert parse(payload(voice_state="dancing")).get("voice_state") is None
    assert parse(payload(voice_state=42)).get("voice_state") is None


# ── hostile input ───────────────────────────────────────────────────────────


def test_rubbish_yields_unknowns_rather_than_an_exception():
    """This parses data that arrived over a network. It must never be the thing
    that takes the integration down."""
    for junk in (None, "", [], 42, {"measurements": "not a dict"}, {"meta": 7}):
        result = parse(junk)
        assert result.get("co2") is None
        assert not result.usable
