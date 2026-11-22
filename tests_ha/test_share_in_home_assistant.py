"""The share screen and the shared set, inside a real Home Assistant."""

from __future__ import annotations

import base64
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.intelleta import api, share, sharing
from custom_components.intelleta.const import (
    CONF_CREDENTIAL,
    CONF_SHARED,
    CONF_SHARED_DEVICES,
    DOMAIN,
    FIELD_SHARED_SCENES,
)

KINDS = ["light", "switch", "fan", "cover", "lock", "climate", "media_player", "scene"]


def _entry(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_CREDENTIAL: "intelleta_test_key"},
        options=options or {},
        version=1,
    )
    entry.add_to_hass(hass)
    return entry


def _fields(result) -> dict:
    return {str(key): (key, value) for key, value in result["data_schema"].schema.items()}


async def test_the_share_screen_is_three_of_home_assistants_own_multi_pick_lists(
    hass: HomeAssistant,
):
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    fields = _fields(result)
    assert list(fields) == [CONF_SHARED, FIELD_SHARED_SCENES, CONF_SHARED_DEVICES]
    for key, selector in fields.values():
        assert key.default() == []  # empty by default
        assert selector.config["multiple"] is True

    # Single things: every kind but scenes, which have a list of their own.
    assert sorted(fields[CONF_SHARED][1].config["domain"]) == sorted(set(KINDS) - {"scene"})
    assert fields[FIELD_SHARED_SCENES][1].config["domain"] == ["scene"]
    # Whole devices: the device list of Home Assistant itself, for devices
    # that hold a light or a switch.
    whole = fields[CONF_SHARED_DEVICES][1]
    assert whole.selector_type == "device"
    assert whole.config["entity"] == [{"domain": ["light", "switch"]}]


async def test_saving_the_screen_stores_what_was_picked(hass: HomeAssistant):
    entry = _entry(hass)
    hass.states.async_set("light.living_lamp", "on", {"friendly_name": "Living lamp"})
    hass.states.async_set("scene.movie_time", "scening", {"friendly_name": "Movie time"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SHARED: ["light.living_lamp"],
            FIELD_SHARED_SCENES: ["scene.movie_time"],
            CONF_SHARED_DEVICES: ["0123456789abcdef0123456789abcdef"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Scenes are saved with the single things, as they always were.
    assert entry.options == {
        CONF_SHARED: ["light.living_lamp", "scene.movie_time"],
        CONF_SHARED_DEVICES: ["0123456789abcdef0123456789abcdef"],
    }


async def test_a_scene_cannot_be_put_in_the_single_things_list(hass: HomeAssistant):
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    try:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHARED: ["scene.movie_time"]}
        )
    except Exception:  # noqa: BLE001 - Home Assistant refuses the field
        assert entry.options == {}
        return
    assert result["type"] is FlowResultType.FORM
    assert entry.options == {}


async def test_the_screen_shows_what_is_already_shared(hass: HomeAssistant):
    entry = _entry(hass, {CONF_SHARED: ["light.living_lamp"]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _fields(result)[CONF_SHARED][0].default() == ["light.living_lamp"]


async def test_a_list_saved_before_this_screen_opens_with_its_scenes_apart(
    hass: HomeAssistant,
):
    """Nothing a customer shared before is lost or moved by the new screen."""
    entry = _entry(hass, {CONF_SHARED: ["light.living_lamp", "scene.movie_time", "lock.door"]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = _fields(result)
    assert fields[CONF_SHARED][0].default() == ["light.living_lamp", "lock.door"]
    assert fields[FIELD_SHARED_SCENES][0].default() == ["scene.movie_time"]
    assert fields[CONF_SHARED_DEVICES][0].default() == []

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SHARED: fields[CONF_SHARED][0].default(),
            FIELD_SHARED_SCENES: fields[FIELD_SHARED_SCENES][0].default(),
            CONF_SHARED_DEVICES: [],
        },
    )
    assert sorted(entry.options[CONF_SHARED]) == sorted(
        ["light.living_lamp", "scene.movie_time", "lock.door"]
    )


def _wall_switch(hass: HomeAssistant, entry, name="Kitchen Lights", gangs=4, area=None):
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", name)}, name=name
    )
    if area is not None:
        devices.async_update_device(device.id, area_id=area.id)
    entities = er.async_get(hass)
    members = []
    for n in range(1, gangs + 1):
        gang = entities.async_get_or_create(
            "switch", "test", f"{name}-{n}", device_id=device.id,
            suggested_object_id=f"{name.lower().replace(' ', '_')}_{n}",
        )
        hass.states.async_set(gang.entity_id, "off", {"friendly_name": f"{name} {n}"})
        members.append(gang.entity_id)
    return device, members


async def test_a_whole_device_is_shared_as_one_thing_with_the_name_of_the_device(
    hass: HomeAssistant,
):
    kitchen = ar.async_get(hass).async_create("Kitchen")
    entry = _entry(hass)
    device, members = _wall_switch(hass, entry, area=kitchen)

    assert share.whole_members(hass, device.id) == sorted(members)
    assert share.collect_whole_things(hass, [device.id]) == [
        {
            "entity": sharing.whole_device_entity(device.id),
            "name": "Kitchen Lights",
            "room": "Kitchen",
        }
    ]


async def test_a_renamed_device_is_shared_under_the_name_the_customer_gave(hass: HomeAssistant):
    entry = _entry(hass)
    device, _ = _wall_switch(hass, entry)
    dr.async_get(hass).async_update_device(device.id, name_by_user="Kitchen")
    [thing] = share.collect_whole_things(hass, [device.id])
    assert thing["name"] == "Kitchen"


async def test_a_whole_device_holds_only_its_lights_and_switches(hass: HomeAssistant):
    """Not a settings toggle, not a hidden or disabled one, not a blind or a
    sensor, and nothing of Intelleta itself."""
    from homeassistant.const import EntityCategory

    entry = _entry(hass)
    device, members = _wall_switch(hass, entry, gangs=2)
    entities = er.async_get(hass)
    lamp = entities.async_get_or_create("light", "test", "lamp", device_id=device.id)
    entities.async_get_or_create(
        "switch", "test", "led", device_id=device.id, entity_category=EntityCategory.CONFIG
    )
    hidden = entities.async_get_or_create("switch", "test", "hidden", device_id=device.id)
    entities.async_update_entity(hidden.entity_id, hidden_by=er.RegistryEntryHider.USER)
    entities.async_get_or_create(
        "switch", "test", "off", device_id=device.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    entities.async_get_or_create("cover", "test", "blind", device_id=device.id)
    entities.async_get_or_create("sensor", "test", "power", device_id=device.id)
    entities.async_get_or_create("switch", DOMAIN, "screen", device_id=device.id)

    assert share.whole_members(hass, device.id) == sorted([*members, lamp.entity_id])


async def test_a_whole_device_that_is_gone_or_holds_nothing_leaves_the_account(
    hass: HomeAssistant,
):
    entry = _entry(hass)
    devices = dr.async_get(hass)
    empty = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "sensor only")}, name="Sensor"
    )
    er.async_get(hass).async_get_or_create("sensor", "test", "t", device_id=empty.id)
    assert share.collect_whole_things(hass, [empty.id, "0" * 32, "Not An Id"]) == []


async def test_what_the_gate_allows_is_what_the_account_is_told(hass: HomeAssistant):
    entry = _entry(hass)
    device, _ = _wall_switch(hass, entry)
    options = {CONF_SHARED: ["light.living_lamp"], CONF_SHARED_DEVICES: [device.id]}
    assert share.shared_ids(options) == [
        "light.living_lamp", sharing.whole_device_entity(device.id)
    ]
    assert share.shared_ids({}) == []


async def test_names_and_rooms_come_from_home_assistant(hass: HomeAssistant):
    areas = ar.async_get(hass)
    living = areas.async_create("Living room")
    kitchen = areas.async_create("Kitchen")
    entry = _entry(hass)

    devices = dr.async_get(hass)
    plug = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "plug")}, name="Plug"
    )
    devices.async_update_device(plug.id, area_id=kitchen.id)

    entities = er.async_get(hass)
    lamp = entities.async_get_or_create("light", "test", "lamp", suggested_object_id="living_lamp")
    entities.async_update_entity(lamp.entity_id, area_id=living.id)
    kettle = entities.async_get_or_create(
        "switch", "test", "kettle", suggested_object_id="kettle", device_id=plug.id
    )
    hass.states.async_set(lamp.entity_id, "on", {"friendly_name": "Living lamp"})
    hass.states.async_set(kettle.entity_id, "off", {"friendly_name": "Kettle"})
    hass.states.async_set("scene.movie_time", "scening", {"friendly_name": "Movie time"})

    things = share.collect_things(
        hass, ["light.living_lamp", "switch.kettle", "scene.movie_time", "light.gone"]
    )
    assert things == [
        {"entity": "light.living_lamp", "name": "Living lamp", "room": "Living room"},
        {"entity": "switch.kettle", "name": "Kettle", "room": "Kitchen"},
        {"entity": "scene.movie_time", "name": "Movie time", "room": None},
    ]


async def test_the_gate_key_is_made_once_and_kept(hass: HomeAssistant, hass_storage):
    first = await share.async_load_gate_key(hass)
    second = await share.async_load_gate_key(hass)
    assert first == second
    assert len(base64.b64decode(first.public_b64)) == 294
    stored = hass_storage[share.GATE_KEY_STORE]["data"]
    assert stored["private_key"] == first.private_pem


class RecordingCloud:
    def __init__(self):
        self.sent = []

    async def async_put_shared(self, body):
        self.sent.append(body)
        return {"things": len(body["things"]), "changed": True}


async def test_the_set_is_sent_once_then_only_on_a_change(hass: HomeAssistant):
    entry = _entry(hass, {CONF_SHARED: ["light.living_lamp"]})
    hass.states.async_set("light.living_lamp", "on", {"friendly_name": "Living lamp"})
    cloud = RecordingCloud()
    publisher = share.SharePublisher(hass, entry, cloud, gate_listening=lambda: True)

    with patch(
        "homeassistant.components.network.async_get_source_ip",
        return_value="192.168.1.10",
    ):
        await publisher.async_check()
        await publisher.async_check()
        await publisher.async_check()
        assert len(cloud.sent) == 1
        body = cloud.sent[0]
        assert body["gate"]["addr"] == "192.168.1.10"
        assert body["gate"]["port"] == 41846
        assert body["integration_version"] == "0.3.3"
        assert body["things"] == [
            {"entity": "light.living_lamp", "name": "Living lamp", "kind": "light", "room": None}
        ]

        hass.states.async_set("light.living_lamp", "on", {"friendly_name": "Reading lamp"})
        await publisher.async_check()
        assert len(cloud.sent) == 2
        assert cloud.sent[-1]["things"][0]["name"] == "Reading lamp"

        hass.config_entries.async_update_entry(entry, options={CONF_SHARED: []})
        await publisher.async_check()
        assert len(cloud.sent) == 3
        assert cloud.sent[-1]["things"] == []


async def test_a_started_integration_sends_once_and_again_when_the_screen_is_saved(
    hass: HomeAssistant,
    socket_enabled,  # noqa: ARG001 - setup also opens the gate's UDP listener
):
    """The wiring in setup: one send at start, one when the screen is saved,
    none for a save that changed nothing."""
    entry = _entry(hass)
    hass.states.async_set("light.living_lamp", "on", {"friendly_name": "Living lamp"})
    sent = []

    async def put(self, body):  # noqa: ARG001
        sent.append(body)
        return {"things": len(body["things"]), "changed": True}

    async def no_devices(self):  # noqa: ARG001
        return []

    async def nobody_announcing(hass):  # noqa: ARG001
        return []

    with (
        patch("custom_components.intelleta.api.CloudClient.async_put_shared", put),
        patch("custom_components.intelleta.api.CloudClient.async_list_devices", no_devices),
        patch("custom_components.intelleta.coordinator.async_discover", nobody_announcing),
        patch(
            "homeassistant.components.network.async_get_source_ip",
            return_value="192.168.1.10",
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(sent) == 1
        assert sent[0]["things"] == []

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHARED: ["light.living_lamp"]}
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(sent) == 2
        assert [t["entity"] for t in sent[1]["things"]] == ["light.living_lamp"]

        # A whole device is added on the same screen: one more thing is sent.
        device, _ = _wall_switch(hass, entry)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_SHARED: ["light.living_lamp"], CONF_SHARED_DEVICES: [device.id]},
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(sent) == 3
        whole = sharing.whole_device_entity(device.id)
        assert {"entity": whole, "name": "Kitchen Lights", "kind": "switch", "room": None} in (
            sent[2]["things"]
        )
        # ... and taken off again: it leaves the account.
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHARED: ["light.living_lamp"], CONF_SHARED_DEVICES: []}
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(sent) == 4
        assert [t["entity"] for t in sent[3]["things"]] == ["light.living_lamp"]

        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SHARED: ["light.living_lamp"]}
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(sent) == 4  # a save that changed nothing sends nothing

        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_nothing_is_reported_while_the_gate_is_not_listening(hass: HomeAssistant):
    """The set carries where devices send their requests. Reported for a
    listener that could not open, every request would go into the void."""
    entry = _entry(hass, {CONF_SHARED: ["light.living_lamp"]})
    hass.states.async_set("light.living_lamp", "on", {"friendly_name": "Living lamp"})
    cloud = RecordingCloud()
    listening = [False]
    publisher = share.SharePublisher(hass, entry, cloud, gate_listening=lambda: listening[0])

    with patch(
        "homeassistant.components.network.async_get_source_ip",
        return_value="192.168.1.10",
    ):
        await publisher.async_check()
        assert cloud.sent == []
        listening[0] = True
        await publisher.async_check()
        assert len(cloud.sent) == 1


class RefusingCloud:
    def __init__(self, error):
        self.error = error
        self.asked = 0

    async def async_put_shared(self, body):  # noqa: ARG002
        self.asked += 1
        raise self.error


async def test_a_body_the_account_refuses_is_not_sent_every_minute(hass: HomeAssistant, caplog):
    entry = _entry(hass, {CONF_SHARED: []})
    for error in (api.Rejected("cloud answered 400", "gate.addr"), api.SharedKeyRefused("refused")):
        cloud = RefusingCloud(error)
        publisher = share.SharePublisher(hass, entry, cloud, gate_listening=lambda: True)
        with patch(
            "homeassistant.components.network.async_get_source_ip",
            return_value="192.168.1.10",
        ):
            for _ in range(5):
                await publisher.async_check()
        assert cloud.asked == 1
    assert "gate.addr" in caplog.text
