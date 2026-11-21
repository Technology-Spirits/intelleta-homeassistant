"""What the customer shares, and when it is sent to the account.

The shared set is the list of things the customer picked on the integration's
"Share with Intelleta" screen. For each one the account receives Home
Assistant's own id, its name, its kind and its room, nothing else. The gate
(this integration) also sends its own address, port and public key, and its
version.

⛔ THE COST RULE: the set is sent once at each start and then only when
something in it changed. A set that has not changed is never sent again. The
tests below prove it.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from conftest import load

sharing = load("sharing")

# The example of the account's `PUT /integration/shared` body, exactly as the
# account's shapes page gives it. The tests build their body through the real
# path and compare against this record, rather than against a hand-made one.
A1_EXAMPLE = """
{
  "integration_version": "0.3.0",
  "gate": { "addr": "192.168.1.10", "port": 41846, "pubkey": "<base64 SubjectPublicKeyInfo, RSA-2048, at most 392 chars>" },
  "things": [
    { "entity": "light.living_lamp", "name": "Living lamp", "kind": "light", "room": "Living room" },
    { "entity": "scene.movie_time", "name": "Movie time", "kind": "scene", "room": null }
  ]
}
"""

PUBKEY = "<base64 SubjectPublicKeyInfo, RSA-2048, at most 392 chars>"


def _example_inputs():
    return [
        {"entity": "scene.movie_time", "name": "Movie time", "room": None},
        {"entity": "light.living_lamp", "name": "Living lamp", "room": "Living room"},
    ]


def _body(things=None, version="0.3.0", addr="192.168.1.10"):
    return sharing.build_shared_body(
        integration_version=version,
        gate_addr=addr,
        gate_port=sharing.GATE_UDP_PORT,
        gate_pubkey=PUBKEY,
        things=_example_inputs() if things is None else things,
    )


def run(coro):
    return asyncio.run(coro)


# ── The kinds that can be shared ─────────────────────────────────────────────


def test_the_eight_kinds_are_the_contract_kinds_and_nothing_else():
    assert sharing.SHAREABLE_KINDS == (
        "light", "switch", "fan", "cover", "lock", "climate", "media_player", "scene",
    )


def test_the_gate_port_is_the_house_port():
    assert sharing.GATE_UDP_PORT == 41846


# ── The body ─────────────────────────────────────────────────────────────────


def test_the_body_matches_the_accounts_own_example_record():
    assert _body() == json.loads(A1_EXAMPLE)


def test_the_kind_is_home_assistants_own_domain_of_the_entity():
    body = _body([{"entity": "media_player.tv", "name": "TV", "room": "Lounge"}])
    assert body["things"] == [
        {"entity": "media_player.tv", "name": "TV", "kind": "media_player", "room": "Lounge"}
    ]


def test_nothing_is_held_back_because_of_its_kind():
    """Owner ruling: every one of the eight kinds can be shared, locks included."""
    things = [
        {"entity": f"{kind}.thing", "name": "Thing", "room": None}
        for kind in sharing.SHAREABLE_KINDS
    ]
    body = _body(things)
    assert [t["kind"] for t in body["things"]] == sorted(sharing.SHAREABLE_KINDS)


def test_a_kind_outside_the_eight_is_never_sent():
    body = _body([
        {"entity": "sensor.temperature", "name": "Temperature", "room": None},
        {"entity": "light.desk", "name": "Desk", "room": None},
    ])
    assert [t["entity"] for t in body["things"]] == ["light.desk"]


def test_an_empty_set_is_a_valid_body():
    """Empty by default: nothing is shared until the customer picks it."""
    assert _body([])["things"] == []


def test_the_order_is_stable_whatever_order_home_assistant_gives():
    """An unchanged set must compare equal, so the order may not wobble."""
    assert _body(_example_inputs()) == _body(list(reversed(_example_inputs())))


def test_only_entity_name_kind_and_room_leave_the_home():
    body = _body([{"entity": "light.a", "name": "A", "room": None, "state": "on",
                   "attributes": {"ip": "10.0.0.2"}}])
    assert set(body["things"][0]) == {"entity", "name", "kind", "room"}
    assert set(body) == {"integration_version", "gate", "things"}
    assert set(body["gate"]) == {"addr", "port", "pubkey"}


def test_a_name_is_sent_exactly_as_written():
    body = _body([{"entity": "light.a", "name": "Lampe du salon é", "room": "Séjour"}])
    assert body["things"][0]["name"] == "Lampe du salon é"
    assert body["things"][0]["room"] == "Séjour"


def test_a_long_name_up_to_the_stored_bound_is_still_sent():
    """The account stores it and marks it as not pickable; that is its call."""
    name = "x" * 255
    body = _body([{"entity": "light.a", "name": name, "room": None}])
    assert body["things"][0]["name"] == name


@pytest.mark.parametrize("bad", [
    {"entity": "light.a", "name": "", "room": None},
    {"entity": "light.a", "name": "x" * 256, "room": None},
    {"entity": "Light.A", "name": "A", "room": None},
    {"entity": "light", "name": "A", "room": None},
    {"entity": "light.a b", "name": "A", "room": None},
    {"entity": "light.a\n", "name": "A", "room": None},
    {"entity": "light." + "a" * 250, "name": "A", "room": None},
    {"entity": "light.a", "name": "half \ud800 a pair", "room": None},
])
def test_a_thing_the_account_would_refuse_is_left_out_not_sent(bad):
    """One bad thing must not make the account refuse the whole set."""
    body = _body([bad, {"entity": "light.ok", "name": "Ok", "room": None}])
    assert [t["entity"] for t in body["things"]] == ["light.ok"]


def test_a_thing_the_account_stores_as_not_pickable_is_still_sent():
    """The account's page: an entity or a name over 96 bytes, or a name with a
    control byte, is stored with pickable false, so the app can show it and say
    it cannot be picked. Left out here, the customer would never see why."""
    long_id = "light." + "a" * 249
    assert len(long_id) == 255
    things = [
        {"entity": long_id, "name": "Long id", "room": None},
        {"entity": "light.b", "name": "bad\x07name", "room": None},
        {"entity": "light.c", "name": "n" * 200, "room": None},
    ]
    assert [t["entity"] for t in _body(things)["things"]] == [long_id, "light.b", "light.c"]


def test_a_room_that_is_not_well_formed_text_is_sent_as_no_room():
    body = _body([{"entity": "light.a", "name": "A", "room": "half \udc00"}])
    assert body["things"][0]["room"] is None


def test_a_room_over_its_bound_is_sent_as_no_room():
    body = _body([{"entity": "light.a", "name": "A", "room": "r" * 97}])
    assert body["things"][0]["room"] is None


def test_an_empty_room_is_no_room():
    body = _body([{"entity": "light.a", "name": "A", "room": ""}])
    assert body["things"][0]["room"] is None


def test_the_same_thing_picked_twice_is_sent_once():
    body = _body([
        {"entity": "light.a", "name": "A", "room": None},
        {"entity": "light.a", "name": "A", "room": None},
    ])
    assert len(body["things"]) == 1


def test_never_more_than_the_accounts_limit():
    things = [{"entity": f"light.l{i:04d}", "name": f"L{i}", "room": None} for i in range(510)]
    assert len(_body(things)["things"]) == sharing.MAX_SHARED_THINGS == 500


# ── When it is sent ──────────────────────────────────────────────────────────


class FakeAccount:
    def __init__(self, fail_with=None):
        self.sent: list[dict] = []
        self.fail_with = fail_with

    async def put(self, body):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(json.loads(json.dumps(body)))
        return {"things": len(body["things"]), "changed": True}


def test_it_is_sent_once_at_start():
    account = FakeAccount()
    sender = _sender()
    assert run(sender.async_push(_body(), account.put)) is True
    assert account.sent == [json.loads(A1_EXAMPLE)]


def test_an_unchanged_set_is_never_sent_again():
    """⛔ THE COST RULE. A minute's check that finds nothing new sends nothing."""
    account = FakeAccount()
    sender = _sender()
    run(sender.async_push(_body(), account.put))
    for _ in range(10):
        assert run(sender.async_push(_body(), account.put)) is False
    assert len(account.sent) == 1


def test_an_unchanged_set_in_another_order_is_not_sent_again():
    account = FakeAccount()
    sender = _sender()
    run(sender.async_push(_body(_example_inputs()), account.put))
    run(sender.async_push(_body(list(reversed(_example_inputs()))), account.put))
    assert len(account.sent) == 1


@pytest.mark.parametrize("change", [
    {"things": [{"entity": "light.living_lamp", "name": "Reading lamp", "room": "Living room"}]},
    {"things": [{"entity": "light.living_lamp", "name": "Living lamp", "room": "Study"}]},
    {"things": []},
    {"version": "0.3.1"},
    {"addr": "192.168.1.11"},
])
def test_a_rename_a_new_room_a_removal_a_new_version_or_address_is_sent(change):
    account = FakeAccount()
    sender = _sender()
    run(sender.async_push(_body(), account.put))
    assert run(sender.async_push(_body(**change), account.put)) is True
    assert len(account.sent) == 2
    assert account.sent[-1] == _body(**change)


def test_a_failed_send_is_tried_again_at_the_next_check():
    sender = _sender()
    down = FakeAccount(fail_with=RuntimeError("the account is away"))
    with pytest.raises(RuntimeError):
        run(sender.async_push(_body(), down.put))
    up = FakeAccount()
    assert run(sender.async_push(_body(), up.put)) is True
    assert len(up.sent) == 1


class Missing(Exception):
    """What the caller's account client raises for a route it does not have."""


class Rejected(Exception):
    """What the caller's account client raises for a body it refuses for good."""


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _sender(clock=None):
    return sharing.SharedSetSender(
        missing=(Missing,), rejected=(Rejected,), clock=clock or Clock()
    )


def test_a_body_the_account_has_no_route_for_is_not_retried_every_minute():
    """Before the account side exists the route answers 404. Asking again each
    minute would cost a request a minute in every home for nothing."""
    clock = Clock()
    sender = _sender(clock)
    missing = FakeAccount(fail_with=Missing("404"))
    assert run(sender.async_push(_body(), missing.put)) is False
    ok = FakeAccount()
    clock.now += 60
    assert run(sender.async_push(_body(), ok.put)) is False
    assert ok.sent == []
    # ...but a change is tried again.
    assert run(sender.async_push(_body(version="0.3.1"), ok.put)) is True


def test_a_route_that_was_missing_is_asked_again_after_an_hour():
    """The account side can ship after the integration. A home whose set never
    changes must still reach it, without a restart."""
    clock = Clock()
    sender = _sender(clock)
    run(sender.async_push(_body(), FakeAccount(fail_with=Missing("404")).put))
    ok = FakeAccount()
    clock.now += sharing.ROUTE_MISSING_RETRY_S - 1
    assert run(sender.async_push(_body(), ok.put)) is False
    clock.now += 1
    assert run(sender.async_push(_body(), ok.put)) is True
    assert len(ok.sent) == 1
    clock.now += sharing.ROUTE_MISSING_RETRY_S * 3
    assert run(sender.async_push(_body(), ok.put)) is False, "accepted: the cost rule again"


def test_the_route_missing_retry_is_hourly():
    assert sharing.ROUTE_MISSING_RETRY_S == 3600


def test_a_body_the_account_rejects_is_not_sent_again_until_it_changes():
    clock = Clock()
    sender = _sender(clock)
    refusing = FakeAccount(fail_with=Rejected("things[0].room"))
    with pytest.raises(Rejected):
        run(sender.async_push(_body(), refusing.put))
    ok = FakeAccount()
    for _ in range(5):
        clock.now += sharing.ROUTE_MISSING_RETRY_S
        assert run(sender.async_push(_body(), ok.put)) is False
    assert ok.sent == []
    assert run(sender.async_push(_body(version="0.3.1"), ok.put)) is True


def test_a_new_start_sends_again_even_when_nothing_changed():
    """Once per start: a new sender is a new start."""
    account = FakeAccount()
    run(_sender().async_push(_body(), account.put))
    run(_sender().async_push(_body(), account.put))
    assert len(account.sent) == 2


def test_the_sender_does_not_keep_a_reference_the_caller_can_change():
    account = FakeAccount()
    sender = _sender()
    body = _body()
    run(sender.async_push(body, account.put))
    body["things"].append({"entity": "light.x", "name": "X", "kind": "light", "room": None})
    assert run(sender.async_push(_body(), account.put)) is False


# ── The address the gate reports ─────────────────────────────────────────────


@pytest.mark.parametrize("addr", ["192.168.1.10", "10.0.0.2", "172.16.4.1"])
def test_a_home_network_address_can_be_reported(addr):
    assert sharing.gate_address_ok(addr)


@pytest.mark.parametrize("addr", [
    None, "", "not an address", "127.0.0.1", "0.0.0.0", "::1", "fe80::1",
    "224.0.0.251", "239.255.255.250", "255.255.255.255",
])
def test_an_address_the_account_refuses_is_never_reported(addr):
    """The account refuses a loopback, multicast or broadcast address with a
    400; reporting one would only cost a refused request."""
    assert not sharing.gate_address_ok(addr)
