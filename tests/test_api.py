"""Card 88 — the two clients, and the one credential rule.

⛔ ONLY THE CLOUD CLIENT CARRIES THE KEY. The local endpoint sits on the
customer's own network and is unauthenticated by ruling, so sending our
credential to an address something on the wifi announced would hand it to
whatever was listening.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from conftest import load

api = load("api")
CloudClient = api.CloudClient
LocalClient = api.LocalClient
CloudDevice = api.CloudDevice
AuthFailed = api.AuthFailed
CloudUnavailable = api.CloudUnavailable

KEY = "intelleta_" + "a" * 43


class FakeResponse:
    def __init__(self, status=200, body=None, raises=None):
        self.status = status
        self._body = body if body is not None else {}
        self._raises = raises

    async def json(self, content_type=None):  # noqa: ARG002
        if self._raises:
            raise self._raises
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records what was asked for, so the credential rule can be asserted."""

    def __init__(self, response=None, raises=None):
        self.response = response or FakeResponse()
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None):  # noqa: ARG002
        self.calls.append((url, headers or {}))
        if self.raises:
            raise self.raises
        return self.response


def run(coro):
    return asyncio.run(coro)


# ── the cloud side ──────────────────────────────────────────────────────────


def test_the_account_list_comes_back_as_devices():
    session = FakeSession(FakeResponse(body={"devices": [
        {"device_id": "aqm-CCBA97047AFC", "name": "Bench", "capabilities": ["co2", "pm"]},
        {"device_id": "aqm-68B6B3250B0C", "name": "Living Room", "capabilities": ["co2"]},
    ]}))
    devices = run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())

    assert [d.device_id for d in devices] == ["aqm-CCBA97047AFC", "aqm-68B6B3250B0C"]
    assert devices[0].capabilities == ("co2", "pm")


def test_the_key_travels_in_the_header_and_never_in_the_address():
    """⛔ Query strings end up in server logs — the same reasoning that put the
    live socket's credential behind a single-use pass."""
    session = FakeSession(FakeResponse(body={"devices": []}))
    run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())

    url, headers = session.calls[0]
    assert KEY not in url, "the credential must not be in the address"
    assert headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_is_distinct_from_an_outage(status):
    """⛔ Home Assistant reacts differently to each: one asks the customer to fix
    something, the other retries quietly. Merging them would either nag people
    about a network blip or silently stop working after a revoke."""
    session = FakeSession(FakeResponse(status=status))
    with pytest.raises(AuthFailed):
        run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())


@pytest.mark.parametrize("status", [500, 502, 404])
def test_a_broken_cloud_is_retryable_not_a_credential_problem(status):
    session = FakeSession(FakeResponse(status=status))
    with pytest.raises(CloudUnavailable):
        run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())


def test_a_captive_portal_answering_html_reads_as_unavailable():
    """⚠ A real thing on customer networks: something intercepts the request and
    returns a login page. It must read as 'cloud unavailable', not crash."""
    session = FakeSession(FakeResponse(raises=ValueError("not json")))
    with pytest.raises(CloudUnavailable):
        run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())


def test_a_network_failure_reads_as_unavailable():
    session = FakeSession(raises=aiohttp.ClientError("no route"))
    with pytest.raises(CloudUnavailable):
        run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())


def test_one_malformed_entry_does_not_cost_the_customer_every_other_cube():
    session = FakeSession(FakeResponse(body={"devices": [
        {"name": "no id at all"},
        "not even a dict",
        {"device_id": "   "},
        {"device_id": "aqm-CCBA97047AFC", "name": "Bench", "capabilities": ["co2"]},
    ]}))
    devices = run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())

    assert [d.device_id for d in devices] == ["aqm-CCBA97047AFC"]


def test_a_cube_with_no_name_falls_back_to_its_identifier():
    session = FakeSession(FakeResponse(body={"devices": [{"device_id": "aqm-CCBA97047AFC"}]}))
    devices = run(CloudClient(session, "https://api.invalid", KEY).async_list_devices())

    assert devices[0].name == "aqm-CCBA97047AFC"
    assert devices[0].capabilities == ()


def test_an_empty_account_is_an_empty_list_not_an_error():
    """Somebody who has signed in but not claimed a cube yet. Their account is
    fine; they simply have nothing."""
    session = FakeSession(FakeResponse(body={"devices": []}))
    assert run(CloudClient(session, "https://api.invalid", KEY).async_list_devices()) == []


def test_the_device_hands_matching_the_plain_dict_it_expects():
    """`matching.reconcile` takes dicts so it can stay free of every import,
    including this one."""
    device = CloudDevice("aqm-X", "Study", ("co2",))
    assert device.as_dict() == {
        "device_id": "aqm-X",
        "name": "Study",
        "capabilities": ["co2"],
    }


# ── the local side ──────────────────────────────────────────────────────────


def test_a_cube_on_the_network_hands_back_its_payload():
    session = FakeSession(FakeResponse(body={"device_id": "aqm-X", "timestamp": 1787725998}))
    got = run(LocalClient(session, "10.0.0.5").async_readings())

    assert got["device_id"] == "aqm-X"


def test_no_credential_is_ever_sent_to_a_local_address():
    """⛔ THE RULE THIS FILE EXISTS FOR. The local endpoint is unauthenticated by
    ruling and sits on a network anything can join. Sending our key to an
    address something announced would hand it to whatever was listening."""
    session = FakeSession(FakeResponse(body={}))
    run(LocalClient(session, "10.0.0.5").async_readings())

    url, headers = session.calls[0]
    assert "Authorization" not in headers
    assert not any("intelleta_" in str(v) for v in headers.values())
    assert "intelleta_" not in url


def test_an_unreachable_cube_is_an_ordinary_None_not_an_exception():
    """⚠ Unreachable is the NORMAL condition the fallback exists to handle.
    Raising would make the ordinary path an exception path."""
    session = FakeSession(raises=aiohttp.ClientError("no route"))
    assert run(LocalClient(session, "10.0.0.5").async_readings()) is None


def test_a_cube_answering_badly_is_also_just_None():
    for response in (FakeResponse(status=404), FakeResponse(status=500),
                     FakeResponse(raises=ValueError("not json"))):
        session = FakeSession(response)
        assert run(LocalClient(session, "10.0.0.5").async_readings()) is None


def test_the_local_call_goes_to_the_readings_path_over_plain_http():
    """Plain http, by ruling: local traffic is unencrypted as local devices
    normally are. Readings only — nothing that could change the cube's state."""
    session = FakeSession(FakeResponse(body={}))
    run(LocalClient(session, "10.0.0.5").async_readings())

    url, _ = session.calls[0]
    assert url == "http://10.0.0.5/readings"
