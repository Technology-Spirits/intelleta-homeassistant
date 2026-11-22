"""The "Share with Intelleta" screen's words, exactly as approved.

Home Assistant draws the screen itself from the options step; the only words
that are ours are its title, its text, and the label and the line under each
of its three lists. They live in strings.json and its English translation.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "intelleta"

TITLE = "Share with Intelleta"
TEXT = (
    "Choose the lights, switches, scenes and other things to share with Intelleta. "
    "In the Intelleta app you then pick up to six on each Intelleta device for Andy to control. "
    "Their names, kinds and rooms are sent to your Intelleta account, and to Google, "
    "which runs Andy's voice, so Andy can recognise them."
)
FIELDS = {
    "shared": "Single things",
    "shared_scenes": "Scenes",
    "shared_devices": "Whole devices from Home Assistant",
}
HELP = {
    "shared": (
        "Each light, switch, fan, blind, lock, thermostat, TV or speaker you pick is "
        "shared on its own."
    ),
    "shared_scenes": (
        "Only your Home Assistant scenes are listed here. Each one you pick is shared "
        "as one thing."
    ),
    "shared_devices": (
        "A wall switch with four lights, for example, becomes one thing for Andy under "
        "its Home Assistant name. Andy switches only its lights and switches, all together."
    ),
}


def _strings(name):
    return json.loads(name.read_text(encoding="utf-8"))


def test_the_share_screen_words_are_the_approved_words():
    for path in (COMPONENT / "strings.json", COMPONENT / "translations" / "en.json"):
        step = _strings(path)["options"]["step"]["init"]
        assert step["title"] == TITLE, path
        assert step["description"] == TEXT, path
        assert step["data"] == FIELDS, path
        assert step["data_description"] == HELP, path


def test_every_list_on_the_screen_has_its_words():
    """The keys are the ones the screen is built with (config_flow.py)."""
    flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    const = (COMPONENT / "const.py").read_text(encoding="utf-8")
    for key in FIELDS:
        assert f'= "{key}"' in const, key
    for name in ("CONF_SHARED,", "FIELD_SHARED_SCENES,", "CONF_SHARED_DEVICES,"):
        assert name in flow, name


def test_the_screen_never_says_device_alone_for_either_kind():
    """Two kinds of device meet on this screen. Ours is "Intelleta device";
    a Home Assistant device is said to be from Home Assistant."""
    step = _strings(COMPONENT / "strings.json")["options"]["step"]["init"]
    assert "each Intelleta device" in step["description"]
    assert step["data"]["shared_devices"].endswith("from Home Assistant")


def test_the_share_screen_names_google():
    """Owner ruling: the box inside Home Assistant names Google."""
    step = _strings(COMPONENT / "strings.json")["options"]["step"]["init"]
    assert "Google" in step["description"]


def test_the_version_was_raised_with_the_share_screen():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    major, minor, patch = (int(part) for part in manifest["version"].split("."))
    assert (major, minor, patch) >= (0, 3, 0)
