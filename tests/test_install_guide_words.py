"""The install guide and the integration's key messages, exactly as approved.

The Intelleta app opens docs/installing.md from its "How to install it" link,
so the guide and the messages inside Home Assistant must say what the app
says. Each test reads the real files a customer sees: the guide as published
and strings.json / translations/en.json as Home Assistant loads them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "intelleta"
GUIDE = ROOT / "docs" / "installing.md"

HACS_GUIDE_URL = "https://hacs.xyz/docs/use/download/download/"

# ── The messages inside Home Assistant (approved words) ──────────────────────
SETUP = (
    "Paste the key from the Intelleta app (Settings › Home Assistant › Make a key). "
    "It is shown once. If you did not copy it, make another."
)
NO_LONGER_ACCEPTED = (
    "Your key is no longer accepted. Make a new one in the Intelleta app "
    "(Settings › Home Assistant › Make a new key) and paste it here."
)
NOT_ACCEPTED = (
    "The key was not accepted. Paste the whole key again, or make a new one in the "
    "Intelleta app (Settings › Home Assistant › Make a new key)."
)

# ── The guide (approved words) ───────────────────────────────────────────────
HACS_INTRO = (
    "HACS (the Home Assistant Community Store) is how Home Assistant installs "
    "integrations made outside its own team. No HACS yet? Install it first by "
    f"following [HACS's own guide]({HACS_GUIDE_URL}), then come back here."
)
SECTION_2 = [
    "In the Intelleta app, go to **Settings → Home Assistant → Make a key**. "
    "There is nothing to type.",
    "Copy the key now, or press **Share** to send it to the computer you use for "
    "Home Assistant. It is shown once and never again. If you lose it, press "
    "**Make a new key** on the same page. The old key stops working.",
]
SECTION_3_LAST = "The Home Assistant page in the app changes to **Connected** on its own."
SECTION_4 = [
    "In Home Assistant, go to **Settings → Devices & services → Intelleta** and "
    "press **Configure**. Under **Shared with Intelleta**, use **Choose entity** to "
    "add each light, switch, scene or other thing you want to share, then press "
    "**Submit**. What you add here leaves your home: its name, kind and room. "
    "Your account also keeps where Home Assistant is on your home network.",
    "Then, in the Intelleta app, open a device, go to **Voice control**, and pick "
    "up to six of them. Say \"Hi Andy, turn on\" and the name. Start every request "
    "to switch something with \"Hi Andy\", even straight after Andy has answered "
    "you. Want more than six? "
    "Make a scene in Home Assistant that does several things at once, and pick the "
    "scene.",
]
ROWS = [
    (
        "The key was not accepted",
        "Part of it was missed when copying, or a newer key replaced it",
        "Paste the whole key again, or make a new one in the Intelleta app",
    ),
    (
        "Your key is no longer accepted",
        "The key was replaced, or Home Assistant was disconnected in the app",
        "Make a new key in the Intelleta app (**Settings → Home Assistant → Make a "
        "new key**) and paste it where Home Assistant asks. Your devices and their "
        "history stay",
    ),
    (
        "Andy says Home Assistant didn't answer",
        "Home Assistant is off, offline, or slow to answer",
        "Check that Home Assistant is on and online. The app's Home Assistant page "
        "shows when it was last heard from",
    ),
    (
        "A thing is missing from the app's list",
        "It is not shared in Home Assistant",
        "Add it under **Intelleta → Configure**",
    ),
    (
        "Andy always says \"Home Assistant didn't answer\", but the app shows Home "
        "Assistant as Connected",
        "The clock on the computer that runs Home Assistant is wrong by more than 30 "
        "seconds. To keep your home safe, Intelleta refuses a request when the "
        "device's clock and Home Assistant's clock disagree",
        "Set that computer to take its time from the internet automatically (often "
        "called \"automatic time\" or NTP). Home Assistant OS does this on its own; "
        "check it if you run Home Assistant on your own computer. Then ask Andy again",
    ),
    (
        "Andy always says \"Home Assistant didn't answer\", and you run Home "
        "Assistant in Docker or another container",
        "Your devices reach Home Assistant on UDP port 41846. The container, or the "
        "computer's firewall, does not let that port in",
        "Run the container with host networking (`network_mode: host`), as Home "
        "Assistant's own guide recommends. Allow UDP port 41846 through the "
        "computer's firewall too. Restart Home Assistant, wait half a minute, then ask Andy again",
    ),
]

# The home-control rows, in the order the guide shows them after the key rows.
HOME_CONTROL_ROWS = [row for row in ROWS if "Andy" in row[0] or row[0].startswith("A thing")]

# The headings the app and older links point at. Sections 1 and 2 were renamed
# on purpose (the card); everything else keeps its anchor.
HEADINGS = [
    "# Installing Intelleta in Home Assistant",
    "## 1. Install Intelleta from HACS",
    "## 2. Make a key",
    "## 3. Connect",
    "## 4. Choose what Andy can control",
    "## What you get",
    "## If your internet goes down",
    "## Troubleshooting",
]


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading + "\n") + len(heading) + 1
    nxt = re.search(r"^#{1,2} ", text[start:], flags=re.MULTILINE)
    return text[start : start + nxt.start()] if nxt else text[start:]


def _paragraphs(block: str) -> list[str]:
    return [p.strip() for p in block.strip().split("\n\n") if p.strip()]


def _rows(text: str) -> list[tuple[str, ...]]:
    table = _section(text, "## Troubleshooting")
    rows = []
    for line in table.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= {"|", "-", " "}:
            continue
        rows.append(tuple(cell.strip() for cell in line.strip("|").split(" | ")))
    return rows[1:]  # drop the header row


# ── strings.json ─────────────────────────────────────────────────────────────


def test_the_three_key_messages_are_the_approved_words():
    for path in (COMPONENT / "strings.json", COMPONENT / "translations" / "en.json"):
        config = json.loads(path.read_text(encoding="utf-8"))["config"]
        assert config["step"]["user"]["description"] == SETUP, path
        assert config["step"]["reauth_confirm"]["description"] == NO_LONGER_ACCEPTED, path
        assert config["error"]["invalid_auth"] == NOT_ACCEPTED, path


# ── The guide ────────────────────────────────────────────────────────────────


def test_the_guide_headings_are_the_ones_links_point_at():
    headings = [line for line in _guide().splitlines() if re.match(r"^#{1,2} ", line)]
    assert headings == HEADINGS


def test_the_opening_says_what_hacs_is_and_links_its_own_guide():
    opening = _paragraphs(_section(_guide(), HEADINGS[0]))[0]
    first, rest = opening.split(". ", 1)
    assert first.startswith("You need Home Assistant with HACS")
    assert rest.startswith(HACS_INTRO), "the HACS sentences follow the first sentence"


def test_section_1_keeps_its_paragraph():
    body = _paragraphs(_section(_guide(), "## 1. Install Intelleta from HACS"))
    assert len(body) == 1
    assert body[0].startswith("In HACS, open **Integrations**")


def test_section_2_is_the_approved_section():
    assert _paragraphs(_section(_guide(), "## 2. Make a key")) == SECTION_2


def test_section_3_ends_with_connected():
    body = _paragraphs(_section(_guide(), "## 3. Connect"))
    assert body[-1].endswith(SECTION_3_LAST)
    assert body[0].startswith("In Home Assistant, go to **Settings → Devices & services")


def test_section_4_is_the_approved_section():
    assert _paragraphs(_section(_guide(), "## 4. Choose what Andy can control")) == SECTION_4


def test_the_approved_troubleshooting_rows_are_there_word_for_word():
    rows = _rows(_guide())
    for row in ROWS:
        assert row in rows, row
    # The two replaced rows appear once each, in their new words only.
    whats = [r[0] for r in rows]
    assert whats.count("The key was not accepted") == 1
    assert whats.count("Your key is no longer accepted") == 1


def test_every_home_control_row_is_an_approved_one():
    """Customer words come only from the approved words. The rows for a wrong
    clock and for a container that cannot hear UDP port 41846 now have approved
    words, so they stand in the guide word for word, after the other rows about
    Andy and Home Assistant, and no other row about them may appear."""
    rows = _rows(_guide())
    for row in rows:
        assert len(row) == 3, row
        if "Andy" in row[0] or "41846" in " ".join(row) or "clock" in row[1]:
            assert row in ROWS, row
    assert rows[-len(HOME_CONTROL_ROWS):] == HOME_CONTROL_ROWS


def test_the_guide_says_a_follow_up_needs_hi_andy():
    """A request to switch something always starts with "Hi Andy", even straight
    after Andy has answered: one sentence, in step 4 only, right after the
    example request."""
    sentence = (
        "Start every request to switch something with \"Hi Andy\", even straight "
        "after Andy has answered you."
    )
    text = _guide()
    assert text.count(sentence) == 1
    step_4 = _section(text, "## 4. Choose what Andy can control")
    assert "Say \"Hi Andy, turn on\" and the name. " + sentence in step_4


def test_nothing_sends_a_person_to_the_old_key_place():
    for text in (
        _guide(),
        (COMPONENT / "strings.json").read_text(encoding="utf-8"),
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"),
    ):
        assert "Integration keys" not in text
        assert not re.search(r"\bmint", text, flags=re.IGNORECASE)


def test_the_guide_carries_no_risk_line():
    """Owner ruling, 20 Nov 2026: no line about risk in the guide; the customer
    agreement only."""
    text = _guide().lower()
    for phrase in ("anyone near the device", "risk", "unsafe"):
        assert phrase not in text, phrase


def test_the_guide_says_device_never_cube():
    assert "cube" not in _guide().lower()
