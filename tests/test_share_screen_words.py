"""The "Share with Intelleta" screen's words, exactly as approved.

Home Assistant draws the screen itself from the options step; the only words
that are ours are its title, its text and the field label, and they live in
strings.json and its English translation.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "intelleta"

TITLE = "Share with Intelleta"
TEXT = (
    "Choose the lights, switches, scenes and other things to share with Intelleta. "
    "In the Intelleta app you then pick up to six on each device for Andy to control. "
    "Their names, kinds and rooms are sent to your Intelleta account, and to Google, "
    "which runs Andy's voice, so Andy can recognise them."
)
FIELD = "Shared with Intelleta"


def _strings(name):
    return json.loads(name.read_text(encoding="utf-8"))


def test_the_share_screen_words_are_the_approved_words():
    for path in (COMPONENT / "strings.json", COMPONENT / "translations" / "en.json"):
        step = _strings(path)["options"]["step"]["init"]
        assert step["title"] == TITLE, path
        assert step["description"] == TEXT, path
        assert step["data"] == {"shared": FIELD}, path


def test_the_share_screen_names_google():
    """Owner ruling: the box inside Home Assistant names Google."""
    step = _strings(COMPONENT / "strings.json")["options"]["step"]["init"]
    assert "Google" in step["description"]


def test_the_version_was_raised_with_the_share_screen():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    major, minor, patch = (int(part) for part in manifest["version"].split("."))
    assert (major, minor, patch) >= (0, 3, 0)
