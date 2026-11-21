"""What the gate asks Home Assistant to do for each kind, and how it knows the
thing really changed.

The device says "It's done" only on a `changed` answer, so `changed` must mean
the thing's state in Home Assistant really reached what was asked. A lock and a
cover are never sent the generic turn on / turn off: in Home Assistant's own
generic road, off on a lock means unlock and on opens a cover.

The home here is a fake with the same three doors the real adapter has: read a
state, call a service, watch a state.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import load

gate = load("gate")


class FakeHome:
    """States, a service table, and watchers, like Home Assistant's own."""

    def __init__(self, states: dict[str, str], *, effect=None, raises=None, delay=0.0):
        self.states = dict(states)
        self.calls: list[tuple[str, str, str]] = []
        self.effect = effect or {}
        self.raises = raises
        self.delay = delay
        self._watchers: dict[str, list] = {}

    def state(self, entity):
        return self.states.get(entity)

    def set_state(self, entity, value):
        self.states[entity] = value
        for callback in list(self._watchers.get(entity, [])):
            callback(value)

    def watch(self, entity, callback):
        self._watchers.setdefault(entity, []).append(callback)
        return lambda: self._watchers[entity].remove(callback)

    async def call(self, domain, service, entity):
        self.calls.append((domain, service, entity))
        if self.raises:
            raise self.raises
        new = self.effect.get((domain, service))
        if new is None:
            return
        if self.delay:
            asyncio.get_running_loop().call_later(self.delay, self.set_state, entity, new)
        else:
            self.set_state(entity, new)


def act(home, entity, action, limit_s=1.0):
    kind = entity.split(".", 1)[0]
    return asyncio.run(gate.act_on(home, entity, kind, action, limit_s))


# ── each kind and each action ───────────────────────────────────────────────

KINDS = [
    # entity, action, state before, the service asked, state after
    ("light.lamp", "on", "off", ("light", "turn_on"), "on"),
    ("light.lamp", "off", "on", ("light", "turn_off"), "off"),
    ("switch.kettle", "on", "off", ("switch", "turn_on"), "on"),
    ("switch.kettle", "off", "on", ("switch", "turn_off"), "off"),
    ("fan.ceiling", "on", "off", ("fan", "turn_on"), "on"),
    ("fan.ceiling", "off", "on", ("fan", "turn_off"), "off"),
    ("cover.curtain", "open", "closed", ("cover", "open_cover"), "opening"),
    ("cover.curtain", "open", "closed", ("cover", "open_cover"), "open"),
    ("cover.curtain", "close", "open", ("cover", "close_cover"), "closing"),
    ("cover.curtain", "close", "open", ("cover", "close_cover"), "closed"),
    ("lock.front_door", "lock", "unlocked", ("lock", "lock"), "locking"),
    ("lock.front_door", "lock", "unlocked", ("lock", "lock"), "locked"),
    ("lock.front_door", "unlock", "locked", ("lock", "unlock"), "unlocking"),
    ("lock.front_door", "unlock", "locked", ("lock", "unlock"), "unlocked"),
    ("climate.hall", "on", "off", ("climate", "turn_on"), "heat"),
    ("climate.hall", "off", "cool", ("climate", "turn_off"), "off"),
    ("media_player.tv", "on", "off", ("media_player", "turn_on"), "idle"),
    ("media_player.tv", "on", "standby", ("media_player", "turn_on"), "playing"),
    ("media_player.tv", "off", "playing", ("media_player", "turn_off"), "off"),
    ("media_player.tv", "off", "on", ("media_player", "turn_off"), "standby"),
]


@pytest.mark.parametrize(("entity", "action", "before", "service", "after"), KINDS)
def test_each_kind_and_action(entity, action, before, service, after):
    home = FakeHome({entity: before}, effect={service: after})
    outcome, _detail = act(home, entity, action)
    assert outcome == "changed"
    assert home.calls == [(*service, entity)]


@pytest.mark.parametrize("action", ["run", "on"])
def test_a_scene_is_run_and_done_means_home_assistant_ran_it(action):
    home = FakeHome({"scene.movie_time": "2026-11-20T17:00:00+00:00"})
    outcome, _detail = act(home, "scene.movie_time", action)
    assert outcome == "changed"
    assert home.calls == [("scene", "turn_on", "scene.movie_time")]


def test_a_scene_home_assistant_refused_is_not_changed():
    home = FakeHome({"scene.movie_time": "unknown"}, raises=RuntimeError("no such scene"))
    outcome, detail = act(home, "scene.movie_time", "run")
    assert outcome == "not_changed"
    assert "refused" in detail


def test_a_lock_or_a_cover_is_never_sent_the_generic_turn_on_or_off():
    for kind in ("lock", "cover"):
        for action in gate.ACTIONS:
            service = gate.service_for(kind, action)
            if service is not None:
                assert service[0] == kind
                assert service[1] not in ("turn_on", "turn_off", "toggle"), (kind, action)
    assert gate.service_for("lock", "on") is None
    assert gate.service_for("lock", "off") is None
    assert gate.service_for("cover", "on") is None
    assert gate.service_for("cover", "off") is None


@pytest.mark.parametrize(
    ("kind", "action"),
    [("light", "open"), ("switch", "lock"), ("fan", "run"), ("climate", "close"),
     ("media_player", "unlock"), ("scene", "off"), ("vacuum", "on"), ("lock", "open")],
)
def test_an_action_that_does_not_fit_has_no_service(kind, action):
    assert gate.service_for(kind, action) is None


# ── changed and not_changed ─────────────────────────────────────────────────


def test_changed_when_the_state_arrives_after_the_call_returns():
    home = FakeHome({"light.lamp": "off"}, effect={("light", "turn_on"): "on"}, delay=0.05)
    assert act(home, "light.lamp", "on")[0] == "changed"


def test_not_changed_when_the_state_does_not_arrive_in_time():
    home = FakeHome({"light.lamp": "off"}, effect={("light", "turn_on"): "on"}, delay=0.5)
    outcome, detail = act(home, "light.lamp", "on", limit_s=0.1)
    assert outcome == "not_changed"
    assert "in time" in detail


def test_not_changed_when_the_state_moves_somewhere_else():
    home = FakeHome({"lock.door": "unlocked"}, effect={("lock", "lock"): "jammed"})
    outcome, _detail = act(home, "lock.door", "lock", limit_s=0.1)
    assert outcome == "not_changed"


def test_not_changed_when_home_assistant_refuses_the_call():
    home = FakeHome({"light.lamp": "off"}, raises=RuntimeError("service not found"))
    outcome, detail = act(home, "light.lamp", "on")
    assert outcome == "not_changed"
    assert "refused" in detail


@pytest.mark.parametrize("state", [None, "unavailable"])
def test_not_changed_and_no_call_when_the_thing_is_unavailable(state):
    home = FakeHome({} if state is None else {"light.lamp": state})
    outcome, detail = act(home, "light.lamp", "on")
    assert outcome == "not_changed"
    assert "unavailable" in detail
    assert home.calls == []


def test_a_thing_already_in_the_asked_state_is_changed_at_once():
    home = FakeHome({"cover.curtain": "open"})
    outcome, _detail = act(home, "cover.curtain", "open")
    assert outcome == "changed"
    assert home.calls == []


def test_a_climate_that_is_unavailable_never_counts_as_on():
    assert not gate.reached("climate", "on", "unavailable")
    assert not gate.reached("media_player", "on", "unknown")
    assert gate.reached("climate", "on", "heat_cool")


def test_the_watch_is_let_go_afterwards():
    home = FakeHome({"light.lamp": "off"}, effect={("light", "turn_on"): "on"})
    act(home, "light.lamp", "on")
    assert home._watchers["light.lamp"] == []
