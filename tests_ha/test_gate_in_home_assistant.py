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

from custom_components.intelleta import gate, receiver, share
from custom_components.intelleta.api import CloudDevice
from custom_components.intelleta.const import CONF_CREDENTIAL, CONF_SHARED, DOMAIN

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
