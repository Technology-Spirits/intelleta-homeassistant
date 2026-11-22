"""The gate's rules: who may ask, for what, and what each request is answered.

This integration is the only thing that decides whether a device's request
switches anything. The checks run in a fixed order and stop at the first that
fails. Two of them are owner rulings that must be proven by a test, not left
to a comment: a thing that is not shared is refused, and a shared thing that is
not on the asking device's own list is refused.

Keys are made here: the vectors' private halves do not exist anywhere.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path

import pytest
from conftest import load
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

gate = load("gate")
api = load("api")

VECTORS = json.loads(
    (Path(__file__).resolve().parent / "home-control-vectors.json").read_text(encoding="utf-8")
)

KITCHEN = "aqm-A1B2C3D4E5F6"
BEDROOM = "aqm-0000000000B2"
SOURCE = ("192.168.1.50", 50123)
START_WALL_MS = 1_763_658_000_000


def _b64_public(private) -> str:
    return base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode("ascii")


DEVICE_KEYS = {
    KITCHEN: rsa.generate_private_key(public_exponent=65537, key_size=2048),
    BEDROOM: rsa.generate_private_key(public_exponent=65537, key_size=2048),
}
STRANGER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
GATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
GATE_PUBLIC = gate.load_public_key(_b64_public(GATE_KEY))

SHARED = {"light.living_lamp", "light.floor", "lock.front_door", "cover.curtain", "scene.movie_time"}
LISTS = {
    KITCHEN: ("light.living_lamp", "lock.front_door", "cover.curtain", "scene.movie_time"),
    BEDROOM: ("light.floor",),
}


def control(device=KITCHEN, *, t=None, id="0f" * 16, entity="light.living_lamp",
            action="on", key=None) -> bytes:
    body = gate.control_body(
        device=device, t=START_WALL_MS + 40_000 if t is None else t, id=id,
        entity=entity, action=action,
    )
    sig = gate.sign(key or DEVICE_KEYS[device], gate.LABEL + body)
    return gate.with_sig(body, base64.b64encode(sig))


class Clock:
    def __init__(self) -> None:
        self.wall = START_WALL_MS
        self.mono = 1000.0

    def advance(self, seconds: float) -> None:
        self.wall += int(seconds * 1000)
        self.mono += seconds


class Harness:
    """A gate with a fake home behind it, past its starting window."""

    def __init__(self, outcome=("changed", "reached on"), *, started=True,
                 shared=SHARED, lists=LISTS, recheck=None) -> None:
        self.clock = Clock()
        self.sent: list[tuple[bytes, tuple]] = []
        self.acted: list[tuple[str, str, str, float]] = []
        self.outcome = outcome
        records = {
            device: gate.device_record(_b64_public(DEVICE_KEYS[device]), lists[device], shared)
            for device in lists
        }

        async def act(entity, kind, action, limit_s):
            self.acted.append((entity, kind, action, limit_s))
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

        async def no_sleep(_s):
            return None

        self.gate = gate.Gate(
            GATE_KEY,
            lookup=records.get,
            act=act,
            send=lambda data, addr: self.sent.append((data, addr)),
            wall_ms=lambda: self.clock.wall,
            mono=lambda: self.clock.mono,
            sleep=no_sleep,
            recheck=recheck,
        )
        if started:
            self.clock.advance(gate.STARTING_S + 10)

    def handle(self, data: bytes, addr=SOURCE) -> None:
        asyncio.run(self.gate.handle(data, addr))

    def answers(self) -> list[dict]:
        out = []
        for data, _addr in self.sent:
            signed, sig = gate.split_signed(data)
            assert gate.verify(GATE_PUBLIC, signed, sig), "every answer is signed by the gate"
            out.append(json.loads(data))
        return out


def _refusal(h: Harness) -> str:
    [answer] = h.answers()
    assert answer["kind"] == "refused"
    assert h.acted == [], "a refusal never acts"
    return answer["why"]


# ── the two owner rulings ───────────────────────────────────────────────────


def test_an_unshared_thing_is_refused():
    """On the device's list, but the customer no longer shares it."""
    h = Harness(shared=SHARED - {"light.living_lamp"})
    h.handle(control(entity="light.living_lamp"))
    assert _refusal(h) == "not_shared"


def test_a_thing_never_shared_is_refused_even_if_the_list_names_it():
    lists = dict(LISTS)
    lists[KITCHEN] = LISTS[KITCHEN] + ("switch.kettle",)
    h = Harness(lists=lists)
    h.handle(control(entity="switch.kettle"))
    assert _refusal(h) == "not_shared"


def test_a_shared_thing_that_is_not_on_the_asking_devices_list_is_refused():
    """light.floor is shared and on the bedroom device's list, not the kitchen's."""
    h = Harness()
    h.handle(control(KITCHEN, entity="light.floor"))
    assert _refusal(h) == "not_on_list"

    h.sent.clear()
    h.handle(control(BEDROOM, id="ab" * 16, entity="light.floor"))
    assert [a["kind"] for a in h.answers()][0] == "taken"


# ── who is asking ───────────────────────────────────────────────────────────


def test_a_bad_signature_gets_no_answer(caplog):
    h = Harness()
    with caplog.at_level(logging.WARNING):
        h.handle(control(KITCHEN, key=STRANGER_KEY))
    assert h.sent == []
    assert h.acted == []
    assert any(KITCHEN in r.getMessage() and "signature" in r.getMessage() for r in caplog.records)


def test_the_altered_vector_gets_no_answer():
    sent: list = []
    acted: list = []

    async def act(*args):
        acted.append(args)
        return ("changed", "reached on")

    mono = [0.0]
    g = gate.Gate(
        GATE_KEY,
        lookup={KITCHEN: gate.device_record(VECTORS["device_pubkey"], ("lock.front_door",), SHARED)}.get,
        act=act, send=lambda d, a: sent.append(d),
        wall_ms=lambda: 1763658000040, mono=lambda: mono[0],
    )
    mono[0] = gate.STARTING_S + 1
    asyncio.run(g.handle(VECTORS["refuse_signature"].encode("utf-8"), SOURCE))
    assert sent == []
    assert acted == []


def test_after_a_bad_signature_that_device_is_ignored_for_the_back_off():
    h = Harness()
    h.handle(control(KITCHEN, key=STRANGER_KEY, id="01" * 16))
    h.clock.advance(1)
    h.handle(control(KITCHEN, id="02" * 16))
    assert h.sent == [], "inside the back-off even a good request is not looked at"

    h.clock.advance(gate.SIGNATURE_BACKOFF_S)
    h.handle(control(KITCHEN, id="03" * 16, t=h.clock.wall))
    assert h.answers()[0]["kind"] == "taken"


def test_a_stranger_is_dropped_before_any_key_work(monkeypatch):
    h = Harness()

    def no_key_work(*_a):
        raise AssertionError("public-key work for a device the gate holds no key for")

    monkeypatch.setattr(gate, "verify", no_key_work)
    h.handle(control("aqm-FFFFFFFFFFFF", key=STRANGER_KEY))
    assert h.sent == []


def test_a_device_the_account_holds_no_key_for_is_dropped():
    h = Harness()
    h.gate._lookup = {KITCHEN: gate.device_record(None, LISTS[KITCHEN], SHARED)}.get
    h.handle(control(KITCHEN))
    assert h.sent == []


# ── a repeat, and replay ────────────────────────────────────────────────────


def test_a_repeat_acts_once():
    """The device sends each request three times; the gate acts once and
    answers every copy with the same bytes."""
    h = Harness()
    request = control()
    h.handle(request)
    first = list(h.sent)
    h.handle(request)
    h.handle(request)

    assert len(h.acted) == 1
    result = first[-1][0]
    assert json.loads(result)["kind"] == "result"
    assert [d for d, _ in h.sent[len(first):]] == [result, result]


def test_a_repeat_while_still_acting_gets_the_taken_answer_again():
    h = Harness()
    request = control()
    release = asyncio.Event()

    async def slow_act(*args):
        h.acted.append(args)
        await release.wait()
        return ("changed", "reached on")

    h.gate._act = slow_act

    async def scenario():
        first = asyncio.create_task(h.gate.handle(request, SOURCE))
        await asyncio.sleep(0)
        await h.gate.handle(request, SOURCE)
        release.set()
        await first

    asyncio.run(scenario())
    kinds = [json.loads(d)["kind"] for d, _ in h.sent]
    assert kinds[:2] == ["taken", "taken"]
    assert h.sent[0][0] == h.sent[1][0]
    assert len(h.acted) == 1


def test_the_same_id_with_different_bytes_is_dropped():
    h = Harness()
    h.handle(control(id="0a" * 16, entity="light.living_lamp"))
    sent = len(h.sent)
    h.handle(control(id="0a" * 16, entity="lock.front_door", action="lock"))
    assert len(h.sent) == sent
    assert len(h.acted) == 1


def test_a_refusal_is_repeated_too_without_judging_again():
    h = Harness()
    request = control(entity="light.floor")
    h.handle(request)
    h.handle(request)
    assert [json.loads(d)["why"] for d, _ in h.sent] == ["not_on_list", "not_on_list"]
    assert h.sent[0][0] == h.sent[1][0]


def test_a_recording_played_after_the_answer_memory_is_refused_by_the_clock():
    h = Harness()
    request = control(t=h.clock.wall)
    h.handle(request)
    h.sent.clear()
    h.clock.advance(gate.MEMORY_S + 1)
    h.handle(request)
    assert _refusal_after_take(h) == "clock"


def _refusal_after_take(h: Harness) -> str:
    [answer] = h.answers()
    assert answer["kind"] == "refused"
    return answer["why"]


def test_the_answer_memory_holds_the_last_32():
    h = Harness()
    first = control(id="%032x" % 1, t=h.clock.wall)
    h.handle(first)
    for n in range(2, 2 + gate.MEMORY_SIZE):
        h.handle(control(id="%032x" % n, t=h.clock.wall + n))
    h.sent.clear()
    h.handle(first)
    assert _refusal_after_take(h) == "clock", "pushed out of memory: judged again, not repeated"
    assert len(h.acted) == 1 + gate.MEMORY_SIZE


# ── starting, and the clock ─────────────────────────────────────────────────


def test_for_the_first_30_seconds_the_gate_answers_starting():
    h = Harness(started=False)
    h.clock.advance(gate.STARTING_S - 1)
    h.handle(control(t=h.clock.wall))
    assert _refusal(h) == "starting"

    h.sent.clear()
    h.clock.advance(2)
    h.handle(control(id="1f" * 16, t=h.clock.wall))
    assert h.answers()[0]["kind"] == "taken"


@pytest.mark.parametrize("skew_ms", [30_001, -30_001])
def test_a_clock_more_than_30_seconds_out_is_refused(skew_ms):
    h = Harness()
    h.handle(control(t=h.clock.wall + skew_ms))
    assert _refusal(h) == "clock"


@pytest.mark.parametrize("skew_ms", [30_000, -30_000])
def test_a_clock_exactly_30_seconds_out_is_taken(skew_ms):
    h = Harness()
    h.handle(control(t=h.clock.wall + skew_ms))
    assert h.answers()[0]["kind"] == "taken"


def test_a_request_older_than_one_already_taken_is_refused():
    h = Harness()
    h.handle(control(id="01" * 16, t=h.clock.wall))
    h.sent.clear()
    h.handle(control(id="02" * 16, t=h.clock.wall))
    assert _refusal_after_take(h) == "clock"


def test_a_refused_request_does_not_move_the_last_time_taken():
    h = Harness()
    h.handle(control(id="01" * 16, t=h.clock.wall + 5, entity="light.floor"))  # not_on_list
    h.sent.clear()
    h.handle(control(id="02" * 16, t=h.clock.wall + 1))
    assert h.answers()[0]["kind"] == "taken"


# ── the action and the kind ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("entity", "action"),
    [("lock.front_door", "on"), ("lock.front_door", "off"), ("cover.curtain", "on"),
     ("cover.curtain", "off"), ("light.living_lamp", "open"), ("light.living_lamp", "lock"),
     ("scene.movie_time", "off")],
)
def test_an_action_that_does_not_fit_the_kind_is_refused(entity, action):
    h = Harness()
    h.handle(control(entity=entity, action=action))
    assert _refusal(h) == "action"


@pytest.mark.parametrize(
    ("entity", "action", "kind"),
    [("light.living_lamp", "on", "light"), ("lock.front_door", "unlock", "lock"),
     ("cover.curtain", "close", "cover"), ("scene.movie_time", "run", "scene"),
     ("scene.movie_time", "on", "scene")],
)
def test_a_fitting_action_is_taken_and_handed_to_home_assistant(entity, action, kind):
    h = Harness()
    h.handle(control(entity=entity, action=action))
    assert h.acted == [(entity, kind, action, gate.CONTROL_LIMIT_MS / 1000)]


# ── taken, then result ──────────────────────────────────────────────────────


def test_changed_is_answered_after_taken_three_times():
    h = Harness(outcome=("changed", "reached on"))
    h.handle(control())
    answers = h.answers()
    assert [a["kind"] for a in answers] == ["taken", "result", "result", "result"]
    assert answers[0]["limit_ms"] == gate.CONTROL_LIMIT_MS == 8000
    assert {a["outcome"] for a in answers[1:]} == {"changed"}
    assert all(a["to"] == KITCHEN and a["id"] == "0f" * 16 for a in answers)


def test_not_changed_is_answered_when_home_assistant_did_not_change_it():
    h = Harness(outcome=("not_changed", "not in time"))
    h.handle(control())
    assert [a.get("outcome") for a in h.answers()[1:]] == ["not_changed"] * 3


def test_an_error_while_acting_is_answered_not_changed():
    h = Harness(outcome=RuntimeError("boom"))
    h.handle(control())
    assert h.answers()[-1]["outcome"] == "not_changed"


def test_the_result_is_sent_at_0_60_and_180_ms():
    h = Harness()
    waits: list[float] = []

    async def sleep(seconds):
        waits.append(seconds)

    h.gate._sleep = sleep
    h.handle(control())
    assert waits == [0.06, 0.12]


def test_answers_go_to_the_requests_source_address_on_port_41846():
    h = Harness()
    h.handle(control(), ("192.168.1.77", 41846))
    h.handle(control(id="1e" * 16, t=START_WALL_MS + 40_001), ("192.168.1.78", 5555))
    assert {addr for _d, addr in h.sent} == {("192.168.1.77", 41846), ("192.168.1.78", 41846)}


def test_answers_carry_the_gates_own_clock():
    h = Harness()
    h.handle(control())
    assert h.answers()[0]["t"] == h.clock.wall


def test_one_log_line_per_request(caplog):
    h = Harness(outcome=("not_changed", "not in time"))
    with caplog.at_level(logging.INFO):
        h.handle(control(entity="lock.front_door", action="lock"))
    lines = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    assert len(lines) == 1
    assert all(word in lines[0] for word in (KITCHEN, "lock.front_door", "lock", "not_changed", "not in time"))


def test_a_refusal_is_one_log_line_too(caplog):
    h = Harness()
    with caplog.at_level(logging.INFO):
        h.handle(control(entity="light.floor"))
    lines = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    assert len(lines) == 1 and "not_on_list" in lines[0] and "light.floor" in lines[0]


# ── from the account's own record, through the real parsing path ───────────

# GET /integration/devices, one device as the account shapes page gives it,
# with the vectors' device key in place of its placeholder.
A2_EXAMPLE = """
{ "device_id": "aqm-A1B2C3D4E5F6", "...": "everything it has today",
  "pubkey": "<base64 SubjectPublicKeyInfo of the device's identity key, or null>",
  "control": ["light.living_lamp", "scene.movie_time"] }
"""


def test_the_vector_request_is_taken_for_a_device_read_from_the_account():
    raw = json.loads(A2_EXAMPLE)
    raw["pubkey"] = VECTORS["device_pubkey"]
    device = api._parse_device(raw)
    record = gate.device_record(device.pubkey, device.control, {"light.living_lamp"})

    sent: list = []
    acted: list = []

    async def act(*args):
        acted.append(args)
        return ("changed", "reached on")

    async def no_sleep(_s):
        return None

    mono = [100.0]
    g = gate.Gate(GATE_KEY, lookup={device.device_id: record}.get, act=act,
                  send=lambda d, a: sent.append(d), wall_ms=lambda: 1763658000040,
                  mono=lambda: mono[0], sleep=no_sleep)
    mono[0] += gate.STARTING_S + 1
    asyncio.run(g.handle(VECTORS["messages"][0]["wire"].encode("utf-8"), SOURCE))

    assert acted == [("light.living_lamp", "light", "on", 8.0)]
    assert [json.loads(d)["kind"] for d in sent] == ["taken", "result", "result", "result"]


def test_the_shapes_page_placeholder_key_holds_no_key():
    device = api._parse_device(json.loads(A2_EXAMPLE))
    assert device.pubkey is None
    assert gate.device_record(device.pubkey, device.control, SHARED) is None


# ── found in review ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("data", [
    b"[1]",
    b"[[1,2,3]]",
    b"[[\"v\"]]",
    b"[]",
    b"[" * 1279 + b"]",
    b"[" * 600 + b"]" * 600,
])
def test_json_that_is_not_an_object_is_dropped_never_raised(data):
    """Anyone on the home network can send these. Each must be dropped
    quietly, never become an error in Home Assistant's log."""
    assert gate.parse_control(data) is None
    h = Harness()
    h.handle(data)
    assert h.sent == [] and h.acted == []


def test_one_devices_id_cannot_shadow_another_devices_request():
    """The answer memory is each device's own: the kitchen device reusing the
    bedroom device's id (ids travel in the clear) does not silence it."""
    h = Harness()
    h.handle(control(KITCHEN, id="5a" * 16, entity="light.living_lamp"))
    h.sent.clear()
    h.handle(control(BEDROOM, id="5a" * 16, entity="light.floor"))
    assert h.answers()[0]["kind"] == "taken"
    assert h.answers()[0]["to"] == BEDROOM


def test_a_request_still_being_acted_on_is_never_pushed_out_of_memory():
    """Its repeat must be answered from memory, not judged again (and refused
    `clock`) while the thing really switches."""
    h = Harness()
    request = control(id="77" * 16, t=h.clock.wall)
    release = asyncio.Event()

    async def slow_act(*args):
        h.acted.append(args)
        await release.wait()
        return ("changed", "reached on")

    h.gate._act = slow_act

    async def scenario():
        first = asyncio.create_task(h.gate.handle(request, SOURCE))
        await asyncio.sleep(0)
        # 32 more requests the gate remembers: refused, each with a new id.
        for n in range(gate.MEMORY_SIZE):
            await h.gate.handle(
                control(id="%032x" % (n + 1), t=h.clock.wall + n + 1, entity="light.floor"),
                SOURCE,
            )
        release.set()
        await first
        h.sent.clear()
        await h.gate.handle(request, SOURCE)

    asyncio.run(scenario())
    [again] = h.answers()
    assert again["kind"] == "result" and again["outcome"] == "changed"
    assert len(h.acted) == 1


def test_recordings_refused_by_the_clock_do_not_push_real_requests_out_of_memory():
    """A neighbour replaying 32 old signed requests must not make the gate
    forget a request it took a moment ago."""
    h = Harness()
    request = control(id="88" * 16, t=h.clock.wall)
    h.handle(request)
    for n in range(gate.MEMORY_SIZE):
        h.handle(control(id="%032x" % (n + 100), t=h.clock.wall - 60_000))
    h.sent.clear()
    h.handle(request)
    [again] = h.answers()
    assert again["kind"] == "result"
    assert len(h.acted) == 1


def test_junk_is_screened_without_starting_any_work():
    """The listener screens each datagram as it arrives and starts work only
    for a well-formed request from a device the gate holds a key for."""
    h = Harness()
    assert h.gate.screen(b"junk", SOURCE) is None
    assert h.gate.screen(control("aqm-FFFFFFFFFFFF", key=STRANGER_KEY), SOURCE) is None
    req = h.gate.screen(control(), SOURCE)
    assert req is not None
    asyncio.run(h.gate.handle_request(*req, SOURCE))
    assert h.answers()[0]["kind"] == "taken"


def test_the_gate_agrees_with_the_rest_of_the_integration():
    """The same facts are written where each module needs them (each loads on
    its own); this keeps them from drifting apart."""
    sharing = load("sharing")
    gate_key = load("gate_key")
    assert gate.DEVICE_PORT == sharing.GATE_UDP_PORT
    assert set(gate._SERVICES) == set(sharing.SHAREABLE_KINDS), (
        "a kind the customer can share but the gate cannot act on, or the other way"
    )
    assert gate.KEY_BITS == gate_key.KEY_BITS
    assert gate.MAX_PUBKEY_CHARS == api.MAX_PUBKEY_CHARS
    assert gate.MAX_ENTITY_BYTES == api.MAX_ENTITY_BYTES == 96


# ── a thing picked a moment ago: the list is read once more ─────────────────
#
# The account pushes a new pick to the device at once, but the gate reads the
# lists only once a minute. Before refusing "not on this device's list", the
# gate asks the account for the list once more.


def _record(device, things, shared=SHARED):
    return gate.device_record(_b64_public(DEVICE_KEYS[device]), things, shared)


class Account:
    """What the account would answer if asked again now."""

    def __init__(self, things=None, *, shared=SHARED, error=None, never=False) -> None:
        self.things = things
        self.shared = shared
        self.error = error
        self.never = never
        self.asked: list[str] = []

    async def __call__(self, device):
        self.asked.append(device)
        if self.never:
            await asyncio.sleep(3600)
        if self.error is not None:
            raise self.error
        return None if self.things is None else _record(device, self.things, self.shared)


def test_a_thing_picked_a_moment_ago_is_taken_after_one_more_look():
    account = Account(LISTS[KITCHEN] + ("light.floor",))
    h = Harness(recheck=account)
    h.handle(control(KITCHEN, entity="light.floor"))
    assert [a["kind"] for a in h.answers()][0] == "taken"
    assert h.acted[0][0] == "light.floor"
    assert account.asked == [KITCHEN]


def test_a_thing_still_not_on_the_list_after_one_more_look_is_refused():
    account = Account(LISTS[KITCHEN])
    h = Harness(recheck=account)
    h.handle(control(KITCHEN, entity="light.floor"))
    assert _refusal(h) == "not_on_list"
    assert account.asked == [KITCHEN]


def test_the_account_is_not_asked_for_a_thing_already_on_the_list():
    account = Account(LISTS[KITCHEN])
    h = Harness(recheck=account)
    h.handle(control(KITCHEN))
    assert account.asked == []


def test_the_account_is_not_asked_for_a_thing_that_is_not_shared():
    """Sharing is read from Home Assistant itself; there is nothing newer to ask for."""
    account = Account(LISTS[KITCHEN] + ("switch.kettle",))
    h = Harness(recheck=account)
    h.handle(control(KITCHEN, entity="switch.kettle"))
    assert _refusal(h) == "not_shared"
    assert account.asked == []


def test_one_more_look_never_lets_through_a_thing_that_is_no_longer_shared():
    account = Account(LISTS[KITCHEN] + ("light.floor",), shared=SHARED - {"light.floor"})
    h = Harness(recheck=account)
    h.handle(control(KITCHEN, entity="light.floor"))
    assert _refusal(h) == "not_on_list"


def test_a_device_that_keeps_asking_costs_one_look_every_few_seconds():
    account = Account(LISTS[KITCHEN])
    h = Harness(recheck=account)
    for n in range(4):
        h.handle(control(KITCHEN, id=f"{n:02x}" * 16, t=h.clock.wall + n, entity="light.floor"))
    assert account.asked == [KITCHEN]
    assert [a["why"] for a in h.answers()] == ["not_on_list"] * 4

    h.clock.advance(gate.LIST_RECHECK_EVERY_S)
    h.handle(control(KITCHEN, id="0e" * 16, t=h.clock.wall, entity="light.floor"))
    assert account.asked == [KITCHEN, KITCHEN]


def test_one_devices_look_does_not_use_up_anothers():
    account = Account(())
    h = Harness(recheck=account)
    h.handle(control(KITCHEN, entity="light.floor"))
    h.handle(control(BEDROOM, id="ab" * 16, entity="light.living_lamp"))
    assert account.asked == [KITCHEN, BEDROOM]


@pytest.mark.parametrize("answer", [Account(None), Account(error=RuntimeError("the account is away"))])
def test_a_look_that_fails_is_a_refusal_not_an_error(answer):
    h = Harness(recheck=answer)
    h.handle(control(KITCHEN, entity="light.floor"))
    assert _refusal(h) == "not_on_list"


def test_a_look_that_takes_too_long_is_a_refusal_within_the_devices_wait(monkeypatch):
    monkeypatch.setattr(gate, "LIST_RECHECK_LIMIT_S", 0.05)

    async def scenario():
        h = Harness(recheck=Account(LISTS[KITCHEN] + ("light.floor",), never=True))
        await h.gate.handle(control(KITCHEN, entity="light.floor"), SOURCE)
        return h

    h = asyncio.run(scenario())
    assert _refusal(h) == "not_on_list"


def test_the_look_ends_well_inside_the_time_a_device_waits_for_an_answer():
    """A device waits 1,000 ms from its first send for `taken` or `refused`,
    and does not ask again before one of them arrives. 0.3.2 allowed 1.5 s:
    on the owner's bench the device had given up, and the gate then took the
    request and switched the thing while Andy said Home Assistant had not
    answered."""
    assert gate.LIST_RECHECK_LIMIT_S <= 0.7


def test_a_look_that_was_too_slow_is_kept_and_the_next_request_is_taken(monkeypatch):
    """Never a late `taken`: the first request is refused in time, the look
    finishes on its own, and asking again is judged against the fresh list
    without asking the account a second time."""
    monkeypatch.setattr(gate, "LIST_RECHECK_LIMIT_S", 0.05)

    async def scenario():
        records = {KITCHEN: _record(KITCHEN, LISTS[KITCHEN])}
        release = asyncio.Event()
        asked = []
        sent, acted = [], []

        async def account(device):
            asked.append(device)
            await release.wait()
            records[device] = _record(device, LISTS[KITCHEN] + ("light.floor",))
            return records[device]

        async def act(entity, kind, action, limit_s):
            acted.append(entity)
            return ("changed", "reached on")

        async def no_sleep(_s):
            return None

        clock = Clock()
        g = gate.Gate(
            GATE_KEY, lookup=records.get, act=act,
            send=lambda data, addr: sent.append(json.loads(data)),
            wall_ms=lambda: clock.wall, mono=lambda: clock.mono, sleep=no_sleep,
            recheck=account,
        )
        clock.advance(gate.STARTING_S + 10)

        await g.handle(control(KITCHEN, t=clock.wall, entity="light.floor"), SOURCE)
        first = list(sent)
        assert acted == [], "nothing is switched by a request that was refused"

        release.set()                      # the account answers, too late for that request
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        clock.advance(3)                   # the person asks again
        sent.clear()
        await g.handle(control(KITCHEN, id="0b" * 16, t=clock.wall, entity="light.floor"), SOURCE)
        return first, list(sent), acted, asked

    first, second, acted, asked = asyncio.run(scenario())
    assert [(a["kind"], a.get("why")) for a in first] == [("refused", "not_on_list")]
    assert second[0]["kind"] == "taken"
    assert acted == ["light.floor"]
    assert asked == [KITCHEN], "the account was asked once, not twice"


def test_a_repeat_that_arrives_during_the_look_is_answered_once():
    """The device asks again after a second; the look is still running."""

    async def scenario():
        release = asyncio.Event()
        asked = []

        async def account(device):
            asked.append(device)
            await release.wait()
            return _record(device, LISTS[KITCHEN] + ("light.floor",))

        h = Harness(recheck=account)
        request = control(KITCHEN, entity="light.floor")
        first = asyncio.ensure_future(h.gate.handle(request, SOURCE))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await h.gate.handle(request, SOURCE)      # the device's one re-ask
        assert h.sent == []                        # nothing yet, and no second look
        release.set()
        await first
        return h, asked

    h, asked = asyncio.run(scenario())
    assert asked == [KITCHEN]
    assert [a["kind"] for a in h.answers()][0] == "taken"
    assert len(h.acted) == 1


def test_a_gate_with_no_way_to_ask_refuses_as_before():
    h = Harness()
    h.handle(control(KITCHEN, entity="light.floor"))
    assert _refusal(h) == "not_on_list"
