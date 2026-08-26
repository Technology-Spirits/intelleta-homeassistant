"""Sending a control to a cube, and knowing what it did. Card 97.

⛔ TWO RULES FROM THE CARD, BOTH ENFORCED HERE RATHER THAN IN EACH ENTITY.

  1. REPORT WHAT THE DEVICE APPLIED, NEVER WHAT WAS ASKED. The cube answers
     every command with the value it actually took — post-validation,
     post-persist. A slider that springs back to the request rather than the
     result is a lie the customer catches immediately, and this programme has
     shipped that defect before: the customer picks, the screen says saved,
     nothing changes.

  2. BRIGHTNESS SETS THE MODE BEFORE THE LEVEL. The cube REFUSES a bare
     brightness unless it is in manual mode — in scheduled the day/night
     schedule governs and in automatic the light sensor does, so a bare request
     is refused rather than applied-until-the-next-boundary. A control that
     ignores this appears to do nothing, INTERMITTENTLY, which is the worst
     kind of bug to be told about second-hand.

⚠ AND THE APPLIED VALUE IS NOT AVAILABLE ON THE CLOUD PATH TODAY. The device
contract says of the settings echo: "Broadcast for UI; platform does not store
it." So until a cube can be reached locally, a control knows what it asked for
and not what the cube did — and rule 1 says the honest answer is then UNKNOWN
rather than the request echoed back. Stated on card 97.

No Home Assistant imports: what to send is a decision, and decisions are worth
testing on their own.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """One command to POST. A control may need more than one, in order."""

    command: str
    params: dict


# The cube accepts only these reporting intervals. ⚠ A whitelist, not a range:
# asking for anything else is refused by the device, so offering a free number
# box would let a customer pick a value that silently does nothing.
POLL_INTERVALS = (30, 60, 120, 300)

BRIGHTNESS_MODES = ("manual", "scheduled", "auto")


def set_brightness(percent: int) -> list[Command]:
    """⛔ TWO COMMANDS, IN THIS ORDER, ALWAYS.

    The cube refuses a bare brightness unless it is already in manual mode. The
    portal has always sent the mode first for exactly this reason; a control
    that sends only the level works on a cube in manual and silently does
    nothing on a cube on a schedule — the same customer, the same slider,
    different behaviour depending on a setting they may not remember making.

    ⚠ SETTING THE MODE IS A REAL CONSEQUENCE, NOT A TECHNICALITY: it takes the
    cube off its day/night schedule. That is what the customer asked for by
    moving a brightness slider, but it is worth saying in the interface rather
    than surprising them at bedtime.
    """
    return [
        Command("brightness_mode", {"mode": "manual"}),
        Command("set_brightness", {"brightness": int(percent)}),
    ]


def set_brightness_mode(mode: str) -> list[Command]:
    if mode not in BRIGHTNESS_MODES:
        raise ValueError(f"unknown brightness mode: {mode!r}")
    return [Command("brightness_mode", {"mode": mode})]


def set_volume(percent: int) -> list[Command]:
    """⚠ ZERO IS VALID AND MEANS SILENT. A truthiness check somewhere in the
    chain would drop it and leave the customer unable to mute the cube — which
    is precisely the setting somebody reaches for at midnight."""
    return [Command("set_volume", {"volume": int(percent)})]


def set_screen_power(on: bool) -> list[Command]:
    return [Command("screen_power", {"on": bool(on)})]


def set_poll_interval(seconds: int) -> list[Command]:
    if seconds not in POLL_INTERVALS:
        raise ValueError(f"unsupported reporting interval: {seconds!r}")
    return [Command("set_poll_interval", {"interval_seconds": int(seconds)})]


def restart() -> list[Command]:
    return [Command("restart", {})]


def refresh_now() -> list[Command]:
    """Ask the cube to publish immediately rather than waiting for its interval.

    ⚠ ITS ACKNOWLEDGEMENT IS THE READING ITSELF. This command deliberately
    produces no status message — the telemetry publish IS the answer — so a
    caller waiting for a status reply would wait for ever.
    """
    return [Command("request_telemetry", {})]


# What a control DISPLAYS: the applied value the cube reported, if it has.
#
# ⛔ EVERY ONE OF THESE READS A `config_` KEY, WHICH ONLY EXISTS BECAUSE THE CUBE
# SAID SO. None of them fall back to a remembered request. That is rule 1, and
# it is why they are gathered here where the pattern is visible rather than
# scattered across four entity classes where one could quietly grow an `or`.
APPLIED_KEYS = {
    "brightness": "config_brightness",
    "brightness_mode": "config_brightness_mode",
    "volume": "config_volume",
    "screen_power": "config_screen_power",
    "poll_interval": "config_poll_interval",
}


def applied_value(readings: object, control: str):
    """What the cube says it is set to, or None for unknown.

    ⛔ None IS A HONEST ANSWER AND MUST STAY REACHABLE. On the cloud path the
    settings echo does not exist at all, so unknown is the truth — and showing
    the last request instead would be the "screen says saved, nothing changed"
    defect wearing a different hat.
    """
    key = APPLIED_KEYS.get(control)
    if key is None or readings is None:
        return None
    return readings.get(key)
