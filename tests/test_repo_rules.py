"""Rules about this repository that a person cannot be relied on to remember.

⚠ These deliberately do NOT import Home Assistant. They check facts about the
tree itself, so they run in seconds and cannot go red for a reason unrelated to
what they are pinning.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "intelleta"


def test_the_device_wire_contract_is_never_vendored_here():
    """⛔ THE RULE FROM CARD 87, AND THE REASON IT IS A TEST.

    Copying the device contract in would feel helpful and cost three things:
    it publishes the device protocol when this repository goes public, it ties
    an integration installed in customers' homes to a contract it cannot be
    upgraded in step with, and it is unnecessary — readings come from the
    cube's local endpoint and everything else from our API.

    A rule in a comment gets read once. This gets checked every push.
    """
    forbidden = {
        "telemetry.schema.json",
        "commands.json",
        "capabilities.md",
        "ota-manifest.schema.json",
        "provisioning-ble.md",
    }
    found = [
        str(p.relative_to(ROOT))
        for p in ROOT.rglob("*")
        if p.is_file() and p.name in forbidden and ".git" not in p.parts
    ]
    assert not found, (
        f"device contract files vendored into this repository: {found}. "
        "Read the docstring above before deleting this test."
    )


def test_the_manifest_says_what_this_actually_is():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == "intelleta"
    assert manifest["config_flow"] is True, "there is no YAML setup path; the flow is the way in"

    # ⛔ local_polling, not cloud_push. Readings come from the cube over the
    # home network (owner ruling 2026-08-25); the cloud is the fallback, not
    # the design. If this ever reads cloud_* again, the design changed and
    # somebody should have said so out loud.
    assert manifest["iot_class"] == "local_polling"

    # Every dependency is a thing installed into a customer's Home Assistant.
    # Keep the list short and deliberate rather than accumulated.
    assert manifest["requirements"] == [], "adding a requirement is a decision, not a convenience"


def test_the_installer_metadata_is_present_and_parses():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["name"]


def test_the_translations_match_the_strings():
    """A missing translation shows the customer a raw key instead of a sentence."""
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert strings == english, (
        "strings.json and translations/en.json have drifted; en.json is the "
        "English rendering of the same keys"
    )


def test_the_manifest_keys_are_in_the_order_home_assistant_demands():
    """⚠ CAUGHT BY CI ON THE VERY FIRST PUSH, so it is pinned here instead.

    Home Assistant's own validator requires `domain`, then `name`, then every
    other key alphabetically. It is a real gate, it fails the build, and the
    message is clear — but it costs a push-and-wait cycle to discover. This
    test makes it a one-second failure on a laptop instead.
    """
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    keys = list(manifest)
    expected = ["domain", "name"] + sorted(
        k for k in keys if k not in ("domain", "name")
    )
    assert keys == expected, (
        "manifest keys must be domain, name, then alphabetical -- "
        f"got {keys}, expected {expected}"
    )


def test_the_installer_file_carries_only_keys_the_installer_accepts():
    """⚠ ALSO CAUGHT BY CI ON THE FIRST PUSH.

    The first version of hacs.json carried `content_in_root` and
    `render_readme`, and the installer rejected the whole file — which then
    cascaded into it being unable to find the manifest at all, reported as the
    confusing "expected a dictionary. Got None".

    Unknown keys are not ignored here. Keep this list to what is actually
    accepted, and add to it deliberately.
    """
    allowed = {
        "name",
        "homeassistant",
        "hacs",
        "zip_release",
        "filename",
        "country",
        "persistent_directory",
        "hide_default_branch",
    }
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    unknown = set(hacs) - allowed
    assert not unknown, f"hacs.json carries keys the installer will reject: {sorted(unknown)}"
