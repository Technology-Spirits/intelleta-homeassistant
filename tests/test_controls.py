"""Card 97 — what a control sends, and what it dares to display.

Two rules from the card, and both have already been broken once in this
programme's history:

  ⛔ Report what the device APPLIED, never what was asked. "The customer picks,
     the screen says saved, nothing changes" is a defect that has shipped here.

  ⛔ Brightness sets the mode BEFORE the level, because the cube refuses a bare
     brightness unless it is in manual mode. A control that ignores this works
     on one cube and silently does nothing on another.
"""

from __future__ import annotations

import pytest
from conftest import load

controls = load("controls")
readings_mod = load("readings")

set_brightness = controls.set_brightness
set_brightness_mode = controls.set_brightness_mode
set_volume = controls.set_volume
set_screen_power = controls.set_screen_power
set_poll_interval = controls.set_poll_interval
restart = controls.restart
refresh_now = controls.refresh_now
applied_value = controls.applied_value
POLL_INTERVALS = controls.POLL_INTERVALS
parse = readings_mod.parse


def names(commands):
    return [c.command for c in commands]


# ── the brightness ordering ─────────────────────────────────────────────────


def test_brightness_sets_the_mode_before_the_level():
    """⛔ THE ORDER IS THE WHOLE POINT. The cube refuses a bare brightness unless
    it is already in manual mode, so a control that sends only the level works
    on a cube in manual and silently does nothing on a cube on a schedule."""
    commands = set_brightness(40)

    assert names(commands) == ["brightness_mode", "set_brightness"]
    assert commands[0].params == {"mode": "manual"}
    assert commands[1].params == {"brightness": 40}


def test_brightness_extremes_survive_intact():
    assert set_brightness(0)[1].params == {"brightness": 0}
    assert set_brightness(100)[1].params == {"brightness": 100}


def test_choosing_a_mode_does_not_drag_a_brightness_with_it():
    """Putting a cube back on its schedule is one instruction, not two."""
    commands = set_brightness_mode("scheduled")

    assert names(commands) == ["brightness_mode"]
    assert commands[0].params == {"mode": "scheduled"}


def test_an_invented_brightness_mode_is_refused_here_not_at_the_cube():
    with pytest.raises(ValueError):
        set_brightness_mode("disco")


# ── the other controls ──────────────────────────────────────────────────────


def test_zero_volume_is_a_real_instruction_and_survives():
    """⚠ ZERO MEANS SILENT, and it is exactly what somebody reaches for at
    midnight. A truthiness check anywhere in this chain would drop it and leave
    the customer unable to mute their cube."""
    commands = set_volume(0)

    assert names(commands) == ["set_volume"]
    assert commands[0].params == {"volume": 0}


def test_the_screen_switch_sends_a_real_boolean_both_ways():
    assert set_screen_power(True)[0].params == {"on": True}
    assert set_screen_power(False)[0].params == {"on": False}


def test_only_the_intervals_the_cube_accepts_can_be_asked_for():
    """⚠ A WHITELIST, NOT A RANGE. Anything else is refused by the device, so a
    free number box would let a customer pick a value that silently does
    nothing."""
    for seconds in POLL_INTERVALS:
        assert set_poll_interval(seconds)[0].params == {"interval_seconds": seconds}

    for unsupported in (45, 15, 3600, 0):
        with pytest.raises(ValueError):
            set_poll_interval(unsupported)


def test_the_buttons_send_what_they_say_and_nothing_else():
    assert names(restart()) == ["restart"]
    assert restart()[0].params == {}
    assert names(refresh_now()) == ["request_telemetry"]


# ── what a control displays ─────────────────────────────────────────────────


def _readings_with_config(**config):
    return parse({
        "device_id": "aqm-CCBA97047AFC",
        "timestamp": 1787725998,
        "config": config,
    })


def test_a_control_shows_what_the_cube_says_it_is_set_to():
    r = _readings_with_config(
        brightness=40, volume=0, brightness_mode="manual", screen_power=True
    )

    assert applied_value(r, "brightness") == 40
    assert applied_value(r, "volume") == 0
    assert applied_value(r, "brightness_mode") == "manual"
    assert applied_value(r, "screen_power") is True


def test_zero_comes_back_as_zero_and_not_as_unknown():
    """The mute case again, from the display side: a muted cube must show muted,
    not blank."""
    r = _readings_with_config(volume=0, brightness=0)

    assert applied_value(r, "volume") == 0
    assert applied_value(r, "brightness") == 0


def test_an_unknown_applied_value_stays_unknown():
    """⛔ THE HONEST ANSWER ON THE CLOUD PATH. The settings echo is broadcast and
    never stored, so a reading fetched from our cloud carries no applied values
    at all. Showing the last REQUEST instead would be the 'screen says saved,
    nothing changed' defect wearing a different hat."""
    r = parse({"device_id": "aqm-X", "timestamp": 1787725998, "measurements": {"co2": 549}})

    for control in ("brightness", "volume", "brightness_mode", "screen_power"):
        assert applied_value(r, control) is None


def test_no_readings_at_all_is_unknown_rather_than_a_crash():
    assert applied_value(None, "brightness") is None


def test_an_unknown_control_name_is_unknown_not_an_error():
    r = _readings_with_config(brightness=40)
    assert applied_value(r, "something_invented") is None


def test_a_nonsense_applied_value_from_the_cube_is_refused():
    """A cube reporting an impossible setting is malfunctioning or the payload
    is corrupt. Either way it must not be displayed as the truth."""
    assert applied_value(_readings_with_config(brightness=400), "brightness") is None
    assert applied_value(_readings_with_config(volume=-10), "volume") is None
    assert applied_value(_readings_with_config(brightness_mode="disco"), "brightness_mode") is None


def test_a_screen_state_that_is_not_a_boolean_is_refused():
    """⚠ Here a real boolean is the ONLY acceptable type — a 1 or a "true" is a
    payload we do not understand rather than one to interpret."""
    for junk in (1, 0, "true", "on", None):
        assert applied_value(_readings_with_config(screen_power=junk), "screen_power") is None


def test_a_setting_can_never_be_confused_with_a_measurement():
    """⚠ They live in one flat namespace, so an applied brightness and a
    hypothetical brightness reading would collide without the prefix."""
    r = parse({
        "device_id": "aqm-X",
        "timestamp": 1787725998,
        "measurements": {"co2": 549},
        "config": {"brightness": 40},
    })

    assert r.get("co2") == 549
    assert r.get("config_brightness") == 40
    assert r.get("brightness") is None, "a setting must not appear under a bare name"
