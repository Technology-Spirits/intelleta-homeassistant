"""Every version gets a numbered release, and its notes are written before the tag.

HACS shows a commit hash instead of a version when a version has no GitHub
release. The notes for the release are kept in docs/release-notes.md so the
person who makes the release copies them rather than writing them on the spot.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "intelleta" / "manifest.json"
NOTES = ROOT / "docs" / "release-notes.md"


def _version() -> str:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def _sections() -> dict[str, str]:
    text = NOTES.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    return {p.split("\n", 1)[0].strip(): p.split("\n", 1)[1] for p in parts}


def test_the_manifest_version_has_release_notes():
    assert f"v{_version()}" in _sections()


def test_the_newest_notes_come_first():
    assert next(iter(_sections())) == f"v{_version()}"


def test_the_notes_never_send_a_person_to_the_old_key_place():
    text = NOTES.read_text(encoding="utf-8")
    assert "Integration keys" not in text
    assert not re.search(r"\bmint", text, flags=re.IGNORECASE)


def test_the_notes_carry_no_line_about_risk():
    # Owner ruling: no risk line in the guide; the release notes link to it.
    text = NOTES.read_text(encoding="utf-8").lower()
    for word in ("risk", "unsafe", "danger"):
        assert word not in text
