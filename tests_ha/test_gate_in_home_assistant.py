"""The gate inside a real Home Assistant: real states, real service calls, real
state-change events, and a real UDP round trip on this machine."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import time
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelleta import gate, receiver, share, sharing
from custom_components.intelleta.api import CloudDevice
from custom_components.intelleta.const import (
    CONF_CREDENTIAL,
    CONF_SHARED,
    CONF_SHARED_DEVICES,
    DOMAIN,
)

DEVICE = "aqm-A1B2C3D4E5F6"
DEVICE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
DEVICE_PUB = base64.b64encode(
    DEVICE_KEY.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
).decode("ascii")


def _service(hass: HomeAssistant, domain: str, service: str, new_state: str | None, calls: list):
    async def handler(call: ServiceCall) -> None:
        calls.append((domain, service))
        entity_ids = call.data["entity_id"]
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        if new_state is not None:
            for entity_id in entity_ids:
                hass.states.async_set(entity_id, new_state)

    hass.services.async_register(domain, service, handler)


async def test_two_callers_at_start_get_the_same_key(hass: HomeAssistant):
    first, second = await asyncio.gather(
        share.async_load_gate_key(hass), share.async_load_gate_key(hass)
    )
    assert first == second


async def test_a_light_is_switched_and_watched_in_home_assistant(hass: HomeAssistant):
    calls: list = []
    _service(hass, "light", "turn_on", "on", calls)
    hass.states.async_set("light.living_lamp", "off")
    outcome, _ = await gate.act_on(receiver.HassHome(hass), "light.living_lamp", "light", "on", 2)
    assert outcome == "changed"
    assert calls == [("light", "turn_on")]
    assert hass.states.get("light.living_lamp").state == "on"


async def test_a_lock_is_locked_with_its_own_service(hass: HomeAssistant):
    calls: list = []
    _service(hass, "lock", "lock", "locked", calls)
    _service(hass, "lock", "turn_on", "unlocked", calls)  # must never be used
    hass.states.async_set("lock.front_door", "unlocked")
    outcome, _ = await gate.act_on(receiver.HassHome(hass), "lock.front_door", "lock", "lock", 2)
    assert outcome == "changed"
    assert calls == [("lock", "lock")]


async def test_a_cover_is_opened_with_its_own_service(hass: HomeAssistant):
    calls: list = []
    _service(hass, "cover", "open_cover", "opening", calls)
    hass.states.async_set("cover.curtain", "closed")
    outcome, _ = await gate.act_on(receiver.HassHome(hass), "cover.curtain", "cover", "open", 2)
    assert outcome == "changed"
    assert calls == [("cover", "open_cover")]


async def test_a_scene_is_run(hass: HomeAssistant):
    calls: list = []
    _service(hass, "scene", "turn_on", None, calls)
    outcome, _ = await gate.act_on(receiver.HassHome(hass), "scene.movie_time", "scene", "run", 2)
    assert outcome == "changed"
    assert calls == [("scene", "turn_on")]


async def test_not_changed_when_the_state_never_arrives(hass: HomeAssistant):
    calls: list = []
    _service(hass, "switch", "turn_on", None, calls)
    hass.states.async_set("switch.kettle", "off")
    outcome, detail = await gate.act_on(receiver.HassHome(hass), "switch.kettle", "switch", "on", 0.2)
    assert outcome == "not_changed"
    assert "in time" in detail


async def test_not_changed_when_home_assistant_has_no_such_service(hass: HomeAssistant):
    hass.states.async_set("fan.ceiling", "off")
    outcome, detail = await gate.act_on(receiver.HassHome(hass), "fan.ceiling", "fan", "on", 1)
    assert outcome == "not_changed"
    assert "refused" in detail


# ── A whole device shared as one thing ──────────────────────────────────────


def _wall_switch(hass: HomeAssistant, kinds=("switch", "switch", "switch", "switch"), state="off"):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    owner = MockConfigEntry(domain="test")
    owner.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={("test", "kitchen")}, name="Kitchen Lights"
    )
    members = []
    for n, kind in enumerate(kinds, start=1):
        gang = er.async_get(hass).async_get_or_create(
            kind, "test", f"kitchen-{n}", device_id=device.id,
            suggested_object_id=f"kitchen_lights_{n}",
        )
        hass.states.async_set(gang.entity_id, state)
        members.append(gang.entity_id)
    return device, members, sharing.whole_device_entity(device.id)


def _switching(hass: HomeAssistant, domain: str, service: str, new_state: str, calls: list,
               stuck: tuple = ()):
    """A service that switches every entity it is given, but the stuck ones."""
    async def handler(call: ServiceCall) -> None:
        entity_ids = call.data["entity_id"]
        entity_ids = [entity_ids] if isinstance(entity_ids, str) else list(entity_ids)
        calls.append((domain, service, sorted(entity_ids)))
        for entity_id in entity_ids:
            if entity_id not in stuck:
                hass.states.async_set(entity_id, new_state)

    hass.services.async_register(domain, service, handler)


async def test_a_whole_device_switches_every_light_on_it_with_one_request(hass: HomeAssistant):
    calls: list = []
    _switching(hass, "switch", "turn_on", "on", calls)
    _, members, whole = _wall_switch(hass)

    outcome, _ = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 2)
    assert outcome == "changed"
    assert calls == [("switch", "turn_on", sorted(members))]
    assert [hass.states.get(m).state for m in members] == ["on"] * 4


async def test_a_whole_device_is_switched_off_all_together(hass: HomeAssistant):
    calls: list = []
    _switching(hass, "switch", "turn_off", "off", calls)
    _, members, whole = _wall_switch(hass, state="on")

    outcome, _ = await gate.act_on(receiver.HassHome(hass), whole, "switch", "off", 2)
    assert outcome == "changed"
    assert [hass.states.get(m).state for m in members] == ["off"] * 4


async def test_a_whole_device_is_not_done_while_one_light_did_not_change(hass: HomeAssistant):
    """Owner: "done" means all of them."""
    calls: list = []
    _, members, whole = _wall_switch(hass)
    _switching(hass, "switch", "turn_on", "on", calls, stuck=(members[2],))

    outcome, detail = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 0.3)
    assert outcome == "not_changed"
    assert "mixed" in detail
    # The others were still switched.
    assert [hass.states.get(m).state for m in members] == ["on", "on", "off", "on"]


async def test_switching_off_is_not_done_when_the_first_light_goes_off(hass: HomeAssistant):
    calls: list = []
    _, members, whole = _wall_switch(hass, state="on")
    _switching(hass, "switch", "turn_off", "off", calls, stuck=(members[0],))

    outcome, _ = await gate.act_on(receiver.HassHome(hass), whole, "switch", "off", 0.3)
    assert outcome == "not_changed"


async def test_a_whole_device_already_all_on_is_done_without_waiting(hass: HomeAssistant):
    _, _, whole = _wall_switch(hass, state="on")
    outcome, detail = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 2)
    assert (outcome, detail) == ("changed", "already on")


async def test_a_whole_device_with_some_lights_on_switches_the_rest(hass: HomeAssistant):
    calls: list = []
    _switching(hass, "switch", "turn_on", "on", calls)
    _, members, whole = _wall_switch(hass)
    hass.states.async_set(members[1], "on")

    outcome, _ = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 2)
    assert outcome == "changed"
    assert [hass.states.get(m).state for m in members] == ["on"] * 4


async def test_lights_and_switches_on_one_device_are_each_asked_in_their_own_words(
    hass: HomeAssistant,
):
    calls: list = []
    _switching(hass, "switch", "turn_on", "on", calls)
    _switching(hass, "light", "turn_on", "on", calls)
    _, members, whole = _wall_switch(hass, kinds=("light", "switch", "light"))

    outcome, _ = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 2)
    assert outcome == "changed"
    assert sorted(calls) == [
        ("light", "turn_on", sorted(m for m in members if m.startswith("light."))),
        ("switch", "turn_on", sorted(m for m in members if m.startswith("switch."))),
    ]


async def test_one_kind_refused_still_switches_the_other_and_is_not_done(hass: HomeAssistant):
    calls: list = []
    _switching(hass, "switch", "turn_on", "on", calls)  # no light.turn_on at all
    _, members, whole = _wall_switch(hass, kinds=("light", "switch"))

    outcome, detail = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 1)
    assert outcome == "not_changed"
    assert "refused" in detail
    assert hass.states.get(members[1]).state == "on"


async def test_a_whole_device_that_cannot_be_read_at_all_is_unavailable(hass: HomeAssistant):
    _, _, whole = _wall_switch(hass, state="unavailable")
    outcome, detail = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 1)
    assert (outcome, detail) == ("not_changed", "unavailable")


async def test_a_whole_device_that_is_gone_is_unavailable(hass: HomeAssistant):
    whole = sharing.whole_device_entity("0" * 32)
    outcome, detail = await gate.act_on(receiver.HassHome(hass), whole, "switch", "on", 1)
    assert (outcome, detail) == ("not_changed", "unavailable")


async def test_the_gate_allows_a_whole_device_the_customer_shares(hass: HomeAssistant):
    device, members, whole = _wall_switch(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_CREDENTIAL: "intelleta_test_key"},
        options={CONF_SHARED: ["light.living_lamp"], CONF_SHARED_DEVICES: [device.id]},
        version=1,
    )
    entry.add_to_hass(hass)
    coordinator = _Coordinator({
        DEVICE: CloudDevice(device_id=DEVICE, name="Kitchen", capabilities=("home_control",),
                            pubkey=DEVICE_PUB, control=(whole,)),
    })
    rx = receiver.GateReceiver(hass, rsa.generate_private_key(public_exponent=65537, key_size=2048))
    rx.add(entry, coordinator)
    record = rx.lookup(DEVICE)
    assert record.shared == frozenset({"light.living_lamp", whole})
    assert record.control == frozenset({whole})
    # A single light of the device is NOT shared just because the whole is.
    assert members[0] not in record.shared


class _Coordinator:
    def __init__(self, devices):
        self.devices = devices


def _entry(hass: HomeAssistant, shared) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_CREDENTIAL: "intelleta_test_key"},
        options={CONF_SHARED: shared}, version=1,
    )
    entry.add_to_hass(hass)
    return entry


async def test_the_gate_answers_over_udp_and_switches_the_lamp(
    hass: HomeAssistant, socket_enabled  # noqa: ARG001
):
    calls: list = []
    _service(hass, "light", "turn_on", "on", calls)
    hass.states.async_set("light.living_lamp", "off")
    hass.states.async_set("light.floor", "off")

    entry = _entry(hass, ["light.living_lamp", "light.floor"])
    coordinator = _Coordinator({
        DEVICE: CloudDevice(device_id=DEVICE, name="Kitchen", capabilities=("home_control",),
                            pubkey=DEVICE_PUB, control=("light.living_lamp",)),
    })
    gate_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rx = receiver.GateReceiver(hass, gate_key)
    rx.add(entry, coordinator)
    assert await rx.async_start(0)
    rx._gate._started -= gate.STARTING_S + 1
    port = rx._transport.get_extra_info("sockname")[1]

    device = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    device.bind(("127.0.0.1", gate.DEVICE_PORT))
    device.setblocking(False)
    loop = asyncio.get_running_loop()

    sent_at = [time.time_ns() // 1_000_000]

    def request(entity: str, id_: str) -> bytes:
        sent_at[0] += 1  # each request later than the one before
        body = gate.control_body(device=DEVICE, t=sent_at[0], id=id_, entity=entity, action="on")
        return gate.with_sig(body, base64.b64encode(gate.sign(DEVICE_KEY, gate.LABEL + body)))

    async def answers(n: int) -> list[dict]:
        got = []
        for _ in range(n):
            data = await asyncio.wait_for(loop.sock_recv(device, 2048), 5)
            signed, sig = gate.split_signed(data)
            assert gate.verify(gate_key.public_key(), signed, sig)
            got.append(json.loads(data))
        return got

    try:
        device.sendto(request("light.living_lamp", "01" * 16), ("127.0.0.1", port))
        got = await answers(4)
        assert [a["kind"] for a in got] == ["taken", "result", "result", "result"]
        assert got[-1]["outcome"] == "changed"
        assert hass.states.get("light.living_lamp").state == "on"

        # Shared, but not on this device's list.
        device.sendto(request("light.floor", "02" * 16), ("127.0.0.1", port))
        [refused] = await answers(1)
        assert refused["why"] == "not_on_list"
        assert hass.states.get("light.floor").state == "off"
        assert calls == [("light", "turn_on")]
    finally:
        device.close()
        rx.stop()


async def test_setup_opens_the_gate_and_unloading_the_last_entry_closes_it(
    hass: HomeAssistant, socket_enabled  # noqa: ARG001
):
    entry = _entry(hass, [])

    async def no_devices(self):  # noqa: ARG001
        return []

    async def nobody_announcing(hass):  # noqa: ARG001
        return []

    async def put(self, body):  # noqa: ARG001
        return {"things": 0, "changed": True}

    with (
        patch("custom_components.intelleta.api.CloudClient.async_put_shared", put),
        patch("custom_components.intelleta.api.CloudClient.async_list_devices", no_devices),
        patch("custom_components.intelleta.coordinator.async_discover", nobody_announcing),
        patch("homeassistant.components.network.async_get_source_ip", return_value="192.168.1.10"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        rx = hass.data[receiver.GATE_DATA]
        assert rx._transport.get_extra_info("sockname")[1] == 41846
        # The gate signs with the same key whose public half is shared.
        key = await share.async_load_gate_key(hass)
        assert rx._gate._key.private_numbers() == serialization.load_pem_private_key(
            key.private_pem.encode("ascii"), password=None
        ).private_numbers()

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert receiver.GATE_DATA not in hass.data


async def test_an_account_that_refused_the_key_holds_no_devices_at_the_gate(hass: HomeAssistant):
    """The customer disconnected Home Assistant in the app: the account
    refuses the key, and the last list held must not switch anything."""
    entry = _entry(hass, ["light.living_lamp"])
    coordinator = _Coordinator({
        DEVICE: CloudDevice(device_id=DEVICE, name="Kitchen", capabilities=("home_control",),
                            pubkey=DEVICE_PUB, control=("light.living_lamp",)),
    })
    rx = receiver.GateReceiver(hass, rsa.generate_private_key(public_exponent=65537, key_size=2048))
    rx.add(entry, coordinator)
    assert rx.lookup(DEVICE) is not None
    coordinator.key_refused = True
    assert rx.lookup(DEVICE) is None
    coordinator.key_refused = False
    assert rx.lookup(DEVICE) is not None


async def test_a_port_that_cannot_be_opened_is_tried_again_and_not_reported(
    hass: HomeAssistant, socket_enabled  # noqa: ARG001
):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = _entry(hass, [])
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("0.0.0.0", 41846))
    try:
        await receiver.async_attach_gate(hass, entry, _Coordinator({}))
        assert not receiver.gate_listening(hass)
    finally:
        blocker.close()

    # The minute's retry runs as a background task in Home Assistant.
    async_fire_time_changed(hass, dt_util.utcnow() + receiver.BIND_RETRY + timedelta(seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert receiver.gate_listening(hass)
    receiver.stop_gate(hass)
    assert receiver.GATE_DATA not in hass.data


async def test_a_gate_stopped_while_its_port_is_opening_does_not_keep_it(
    hass: HomeAssistant, socket_enabled  # noqa: ARG001
):
    """The last entry unloads while a retry is opening the port: the port
    must be let go, or the next start finds it taken by nobody."""
    rx = receiver.GateReceiver(hass, rsa.generate_private_key(public_exponent=65537, key_size=2048))
    real_open = hass.loop.create_datagram_endpoint
    opened = []

    async def open_then_stop(*args, **kwargs):
        transport, protocol = await real_open(*args, **kwargs)
        opened.append(transport)
        rx.stop()  # the unload lands while the open is in flight
        return transport, protocol

    with patch.object(hass.loop, "create_datagram_endpoint", open_then_stop):
        assert not await rx.async_start(0)
    assert not rx.listening
    assert opened and opened[0].is_closing()


async def test_removing_the_last_entry_stops_a_gate_that_failed_to_unload(
    hass: HomeAssistant, socket_enabled  # noqa: ARG001
):
    """A gate left running would sign with the removed key while a new one is
    shared, and every device would reject its answers."""
    from custom_components.intelleta import async_remove_entry

    entry = _entry(hass, [])
    await receiver.async_attach_gate(hass, entry, _Coordinator({}))
    assert receiver.gate_listening(hass)
    await hass.config_entries.async_remove(entry.entry_id)
    await async_remove_entry(hass, entry)
    assert receiver.GATE_DATA not in hass.data
