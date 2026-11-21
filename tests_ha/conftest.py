"""Tests that need a real Home Assistant.

⚠ NOT PART OF `pytest tests/`, and not run in CI. Home Assistant's test harness
(pytest-homeassistant-custom-component) does not run on Windows, so these live
apart from the main suite and are run on Linux (docs/maintaining.md has a
container command that works):

    pytest tests_ha -o asyncio_mode=auto

They exist to check the parts the plain tests cannot reach: the options screen
as Home Assistant builds it, and reading names and rooms out of Home
Assistant's own registries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("pytest_homeassistant_custom_component")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):  # noqa: ARG001
    yield


@pytest.fixture(autouse=True)
def network_dependencies_as_loaded(hass):
    """zeroconf and network open real sockets, which the harness forbids.
    Nothing here tests them, so they are marked as already set up."""
    hass.config.components.update({"zeroconf", "network"})
    yield


@pytest.fixture(autouse=True)
def gate_port_let_go_after_each_test(hass):
    """The gate listens on the real UDP port, which outlives one test's Home
    Assistant. A test that fails before it stops the gate would leave the
    port taken, and every later test that opens it would fail too. Tests
    that check the gate closes assert it themselves before this runs."""
    yield
    from custom_components.intelleta import receiver

    receiver.stop_gate(hass)
