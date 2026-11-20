"""The gate: a device on the home network asks this integration to switch a
thing, and this integration alone decides.

A person says "Hi Andy, turn on Living lamp" to an Intelleta device. The
device sends one signed UDP datagram to this integration (`control`). The
integration checks who is asking and whether that device may switch that
thing, answers `taken` (or `refused`), asks Home Assistant to do it, watches
the thing's state really change, and answers `result`. Nothing about the
action passes through our cloud.

⛔ THIS IS THE ONLY GATE. The device's own list is a convenience for the voice
model; it decides nothing. A thing the customer did not share on the "Share
with Intelleta" screen cannot be touched, and a shared thing that is not on
the asking device's own list cannot be touched by that device. Both are tests.

The protection is two keys, never the secrecy of this format (this code is
public):

  * a device signs its request with its own identity key; this integration
    verifies it with the public half the account hands over on
    `GET /integration/devices`, and keeps the last copy it read, so a request
    is still judged correctly while the account cannot be reached;
  * this integration signs its answers with its own key pair (gate_key.py),
    whose public half the account hands to the devices.

Both are RSASSA-PSS, SHA-256, MGF1 SHA-256, 32-byte salt, over the label
`aqm-home-control/1` and a line feed, then the message's bytes up to its
signature field, closed with `}`.

⚠ THIS MODULE IMPORTS NOTHING OF HOME ASSISTANT, so every rule here is tested
on any machine. `receiver.py` binds the UDP port and is the adapter between
this and Home Assistant's states and services.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import functools
import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_LOGGER = logging.getLogger(__name__)

# ── The numbers. Each one is a named setting. ──────────────────────────────

# ⚠ HOW LONG THE GATE WATCHES FOR THE CHANGE before it answers not_changed.
# A placeholder until the bench proof measures a real number; the protocol
# allows 1000 to 30000.
CONTROL_LIMIT_MS = 8000

# The two clocks must agree to within this, and a device's requests must move
# forward in time.
CLOCK_WINDOW_MS = 30_000

# For this long after the gate starts it answers every request `starting`. It
# outlasts the clock window, so a request recorded just before a restart
# cannot be played back after it (the answer memory and the last time taken
# are lost on a restart).
STARTING_S = 30

# The answer memory: the last 32 requests, each kept 60 seconds. A repeat of a
# request in it is answered with its latest answer, byte for byte, and never
# acted on twice.
MEMORY_SIZE = 32
MEMORY_S = 60

# After a signature fails, requests naming that device are not looked at for
# this long, so a neighbour cannot make the gate do unbounded key work under a
# real device's (public) id. An engineering default; the protocol names no
# number.
SIGNATURE_BACKOFF_S = 10

# `result` is sent three times, at 0, 60 and 180 ms, so a lost datagram costs
# nothing.
RESULT_SENDS_MS = (0, 60, 180)

# The datagram limit, and the port a device listens on for the answer.
MAX_DATAGRAM = 1280
DEVICE_PORT = 41846

LABEL = b"aqm-home-control/1\n"

KINDS = ("light", "switch", "fan", "cover", "lock", "climate", "media_player", "scene")
ACTIONS = ("on", "off", "open", "close", "lock", "unlock", "run")
OUTCOMES = ("changed", "not_changed")
WHYS = ("not_shared", "not_on_list", "action", "clock", "starting")

_FIELDS = {
    "control": ("v", "kind", "from", "t", "id", "entity", "action", "sig"),
    "taken": ("v", "kind", "to", "t", "id", "limit_ms", "sig"),
    "result": ("v", "kind", "to", "t", "id", "outcome", "sig"),
    "refused": ("v", "kind", "to", "t", "id", "why", "sig"),
}

_DEVICE_RE = re.compile(r"^aqm-[0-9A-F]{12}\Z")
_ID_RE = re.compile(r"^[0-9a-f]{32}\Z")
_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\Z")
_SIG_RE = re.compile(r"^[A-Za-z0-9+/]{342}==\Z")
_SIG_MARK = b',"sig":"'

_PSS = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32)
_KEY_BITS = 2048
_MAX_PUBKEY_CHARS = 392


# ── The wire: canonical form and signatures ────────────────────────────────


def _value(v: object) -> bytes:
    if isinstance(v, bool):
        raise ValueError("no booleans on this wire")
    if isinstance(v, int):
        return str(v).encode("ascii")
    if isinstance(v, str):
        if any(c in v for c in '"\\') or any(ord(c) < 0x20 or ord(c) == 0x7F for c in v):
            raise ValueError("strings on this wire carry no escapes")
        return b'"' + v.encode("utf-8") + b'"'
    raise ValueError(f"no {type(v).__name__} on this wire")


def _body(kind: str, values: dict) -> bytes:
    """The canonical bytes of a message without its signature, closed with `}`.

    These are exactly the bytes that are signed (after the label).
    """
    names = _FIELDS[kind][:-1]
    return (
        b"{"
        + b",".join(b'"' + n.encode("ascii") + b'":' + _value(values[n]) for n in names)
        + b"}"
    )


def control_body(*, device: str, t: int, id: str, entity: str, action: str) -> bytes:  # noqa: A002
    return _body(
        "control",
        {"v": 1, "kind": "control", "from": device, "t": t, "id": id,
         "entity": entity, "action": action},
    )


def answer_body(kind: str, *, to: str, t: int, id: str, **extra: object) -> bytes:  # noqa: A002
    if kind not in ("taken", "result", "refused"):
        raise ValueError(kind)
    return _body(kind, {"v": 1, "kind": kind, "to": to, "t": t, "id": id, **extra})


def with_sig(body: bytes, sig_b64: bytes) -> bytes:
    """The wire bytes: the body with the signature as its last field."""
    return body[:-1] + _SIG_MARK + sig_b64 + b'"}'


def split_signed(wire: bytes) -> tuple[bytes, bytes]:
    """(what was signed, the raw signature) of any message on this wire.

    Raises ValueError for bytes that do not end in a signature field.
    """
    at = wire.rfind(_SIG_MARK)
    if at < 0 or not wire.endswith(b'"}'):
        raise ValueError("no signature field")
    sig_b64 = wire[at + len(_SIG_MARK):-2]
    try:
        sig = base64.b64decode(sig_b64, validate=True)
    except (binascii.Error, ValueError) as err:
        raise ValueError("signature is not base64") from err
    return LABEL + wire[:at] + b"}", sig


def sign(private_key: rsa.RSAPrivateKey, message: bytes) -> bytes:
    return private_key.sign(message, _PSS, hashes.SHA256())


def verify(public_key: rsa.RSAPublicKey, message: bytes, sig: bytes) -> bool:
    try:
        public_key.verify(sig, message, _PSS, hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def sign_answer(private_key: rsa.RSAPrivateKey, kind: str, **fields: object) -> bytes:
    body = answer_body(kind, **fields)
    return with_sig(body, base64.b64encode(sign(private_key, LABEL + body)))


@functools.lru_cache(maxsize=64)
def load_public_key(b64: str | None) -> rsa.RSAPublicKey | None:
    """An RSA-2048 public key from base64 DER SubjectPublicKeyInfo, else None."""
    if not isinstance(b64, str) or not 0 < len(b64) <= _MAX_PUBKEY_CHARS:
        return None
    try:
        der = base64.b64decode(b64, validate=True)
        key = serialization.load_der_public_key(der)
    except (binascii.Error, ValueError, TypeError):
        return None
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != _KEY_BITS:
        return None
    return key


@dataclass(frozen=True)
class Control:
    """A device's request, read whole and in canonical form."""

    device: str
    t: int
    id: str
    entity: str
    action: str
    sig: bytes
    signed: bytes
    raw: bytes


def _no_duplicates(pairs: list) -> list:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a field given twice")
    return pairs


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_control(data: bytes) -> Control | None:
    """The request in `data`, or None for anything out of shape.

    ⛔ READ, THEN REFUSE; NEVER CLIP. A field over its bound, a wrong type, a
    missing field, an extra field, fields out of order, whitespace or an
    escape: the whole datagram is dropped. The bytes are rebuilt from what was
    read and must equal what arrived.
    """
    if not isinstance(data, bytes | bytearray) or not 0 < len(data) <= MAX_DATAGRAM:
        return None
    data = bytes(data)
    try:
        pairs = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(pairs, list) or [k for k, _ in pairs] != list(_FIELDS["control"]):
        return None
    f = dict(pairs)

    entity, sig = f["entity"], f["sig"]
    if not (
        _is_int(f["v"]) and f["v"] == 1
        and f["kind"] == "control"
        and isinstance(f["from"], str) and _DEVICE_RE.match(f["from"])
        and _is_int(f["t"]) and 10**12 <= f["t"] < 10**13
        and isinstance(f["id"], str) and _ID_RE.match(f["id"])
        and isinstance(entity, str) and _ENTITY_RE.match(entity)
        and 3 <= len(entity.encode("utf-8")) <= 96
        and f["action"] in ACTIONS
        and isinstance(sig, str) and _SIG_RE.match(sig)
    ):
        return None
    try:
        raw_sig = base64.b64decode(sig, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw_sig) != 256 or base64.b64encode(raw_sig).decode("ascii") != sig:
        return None

    body = control_body(device=f["from"], t=f["t"], id=f["id"], entity=entity, action=f["action"])
    if with_sig(body, sig.encode("ascii")) != data:
        return None
    return Control(
        device=f["from"], t=f["t"], id=f["id"], entity=entity, action=f["action"],
        sig=raw_sig, signed=LABEL + body, raw=data,
    )


# ── The actions, by kind ───────────────────────────────────────────────────
#
# ⛔ A LOCK AND A COVER ARE NEVER SENT turn_on OR turn_off. In Home Assistant's
# generic road "off" on a lock means unlock and "on" opens a cover. Each kind
# is asked in its own words, for the action the person asked for.

_SERVICES: dict[str, dict[str, tuple[str, str]]] = {
    "light": {"on": ("light", "turn_on"), "off": ("light", "turn_off")},
    "switch": {"on": ("switch", "turn_on"), "off": ("switch", "turn_off")},
    "fan": {"on": ("fan", "turn_on"), "off": ("fan", "turn_off")},
    "cover": {"open": ("cover", "open_cover"), "close": ("cover", "close_cover")},
    "lock": {"lock": ("lock", "lock"), "unlock": ("lock", "unlock")},
    "climate": {"on": ("climate", "turn_on"), "off": ("climate", "turn_off")},
    "media_player": {"on": ("media_player", "turn_on"), "off": ("media_player", "turn_off")},
    "scene": {"run": ("scene", "turn_on"), "on": ("scene", "turn_on")},
}

_NO_STATE = ("unavailable", "unknown")


def service_for(kind: str, action: str) -> tuple[str, str] | None:
    """The Home Assistant service for this action on this kind, or None when
    the action does not fit the kind."""
    return _SERVICES.get(kind, {}).get(action)


def reached(kind: str, action: str, state: str | None) -> bool:
    """Whether the thing's state is what the action asked for.

    A cover or a lock that has started to move counts: for a slow curtain,
    "it is doing it" is the honest moment to say it is done.
    """
    if state is None or state in _NO_STATE:
        return False
    if kind in ("light", "switch", "fan"):
        return state == action
    if kind == "cover":
        return state in {"open": ("open", "opening"), "close": ("closed", "closing")}.get(action, ())
    if kind == "lock":
        return state in {"lock": ("locked", "locking"), "unlock": ("unlocked", "unlocking")}.get(action, ())
    if kind == "climate":
        return state != "off" if action == "on" else state == "off"
    if kind == "media_player":
        off = ("off", "standby")
        return state not in off if action == "on" else state in off
    return False


class Home(Protocol):
    """The three things the gate needs of Home Assistant (receiver.py)."""

    def state(self, entity: str) -> str | None: ...
    async def call(self, domain: str, service: str, entity: str) -> None: ...
    def watch(self, entity: str, callback: Callable[[str], None]) -> Callable[[], None]: ...


async def act_on(home: Home, entity: str, kind: str, action: str, limit_s: float) -> tuple[str, str]:
    """Do it, watch it, and say what happened: (outcome, the reason for the log).

    `changed` only when the state really reached what was asked (or, for a
    scene, Home Assistant ran it). `not_changed` when it did not in time, the
    thing is unavailable, or Home Assistant refused the call; the reason says
    which.
    """
    service = service_for(kind, action)
    if service is None:
        return "not_changed", "the action does not fit the kind"

    if kind == "scene":
        try:
            async with asyncio.timeout(limit_s):
                await home.call(*service, entity)
        except TimeoutError:
            return "not_changed", "not run in time"
        except Exception as err:  # noqa: BLE001
            return "not_changed", f"refused by Home Assistant: {err}"
        return "changed", "run"

    now = home.state(entity)
    if now is None or now == "unavailable":
        return "not_changed", "unavailable"
    if reached(kind, action, now):
        return "changed", f"already {now}"

    arrived = asyncio.Event()

    def on_change(new_state: str) -> None:
        if reached(kind, action, new_state):
            arrived.set()

    # Watched before the call, so a change during the call is not missed.
    unwatch = home.watch(entity, on_change)
    try:
        async with asyncio.timeout(limit_s):
            try:
                await home.call(*service, entity)
            except TimeoutError:
                raise
            except Exception as err:  # noqa: BLE001
                return "not_changed", f"refused by Home Assistant: {err}"
            if not reached(kind, action, home.state(entity)):
                await arrived.wait()
    except TimeoutError:
        return "not_changed", f"not in time (state {home.state(entity)})"
    finally:
        unwatch()
    return "changed", f"reached {home.state(entity)}"


# ── The rules ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeviceRecord:
    """What the gate holds for one device of the account."""

    key: rsa.RSAPublicKey
    control: frozenset[str]
    shared: frozenset[str]


def device_record(
    pubkey_b64: str | None, control: Iterable[str], shared: Iterable[str]
) -> DeviceRecord | None:
    """The gate's record of a device, or None when it holds no usable key for
    it (such a device is a stranger: dropped before any key work)."""
    key = load_public_key(pubkey_b64)
    if key is None:
        return None
    return DeviceRecord(key=key, control=frozenset(control), shared=frozenset(shared))


@dataclass
class _Remembered:
    request: bytes
    answer: bytes
    at: float


Act = Callable[[str, str, str, float], Awaitable[tuple[str, str]]]


class Gate:
    """Judges each datagram in a fixed order and stops at the first failure.

    1. shape; 2. a device the gate holds a key for; 3. a repeat (answered from
    memory, never acted on twice); 4. the signature; 5. starting; 6. the clock,
    never backwards; 7. shared; 8. on this device's list; 9. the action fits
    the kind; 10. take it, act, watch, answer.

    Nothing before step 4 does any public-key work, and nothing is ever
    answered for a request whose signature did not verify.
    """

    def __init__(
        self,
        private_key: rsa.RSAPrivateKey,
        *,
        lookup: Callable[[str], DeviceRecord | None],
        act: Act,
        send: Callable[[bytes, tuple], None],
        wall_ms: Callable[[], int] = lambda: int(time.time() * 1000),
        mono: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        limit_ms: int = CONTROL_LIMIT_MS,
        log: logging.Logger = _LOGGER,
    ) -> None:
        if not 1000 <= limit_ms <= 30000:
            raise ValueError("limit_ms must be 1000 to 30000")
        self._key = private_key
        self._lookup = lookup
        self._act = act
        self._send = send
        self._wall_ms = wall_ms
        self._mono = mono
        self._sleep = sleep
        self._limit_ms = limit_ms
        self._log = log
        self._started = mono()
        self._memory: OrderedDict[str, _Remembered] = OrderedDict()
        self._last_t: dict[str, int] = {}
        self._backoff_until: dict[str, float] = {}

    # The memory ------------------------------------------------------------

    def _forget_old(self, now: float) -> None:
        while self._memory:
            first = next(iter(self._memory.values()))
            if now - first.at < MEMORY_S:
                break
            self._memory.popitem(last=False)

    def _remember(self, req: Control, answer: bytes, now: float) -> None:
        while len(self._memory) >= MEMORY_SIZE:
            self._memory.popitem(last=False)
        self._memory[req.id] = _Remembered(req.raw, answer, now)

    # Answers ---------------------------------------------------------------

    def _answer(self, kind: str, req: Control, **extra: object) -> bytes:
        return sign_answer(self._key, kind, to=req.device, t=self._wall_ms(), id=req.id, **extra)

    def _refuse(self, req: Control, why: str, addr: tuple, now: float) -> None:
        answer = self._answer("refused", req, why=why)
        self._remember(req, answer, now)
        self._send(answer, addr)
        self._log.info(
            "home control: %s asked %s %s: refused (%s)", req.device, req.action, req.entity, why
        )

    # The order of checks ---------------------------------------------------

    async def handle(self, data: bytes, source: tuple) -> None:
        """One datagram from `source` (address, port)."""
        req = parse_control(data)                                      # 1. shape
        if req is None:
            self._log.debug("home control: dropped a datagram out of shape from %s", source[0])
            return
        record = self._lookup(req.device)                              # 2. not a stranger
        if record is None:
            self._log.debug("home control: dropped a request naming %s, a device with no key here", req.device)
            return
        # Answers go to the request's source address, on the device's port.
        addr = (source[0], DEVICE_PORT)

        now = self._mono()
        self._forget_old(now)
        kept = self._memory.get(req.id)                                # 3. a repeat
        if kept is not None:
            if kept.request == req.raw:
                self._send(kept.answer, addr)
                self._log.debug("home control: %s repeated %s; answered again", req.device, req.id)
            else:
                self._log.debug("home control: %s reused %s with other bytes; dropped", req.device, req.id)
            return

        if self._backoff_until.get(req.device, 0.0) > now:             # 4. the signature
            self._log.debug("home control: %s is in its back-off; dropped", req.device)
            return
        if not verify(record.key, req.signed, req.sig):
            self._backoff_until[req.device] = now + SIGNATURE_BACKOFF_S
            self._log.warning(
                "home control: a request naming %s from %s failed its signature; "
                "nothing done, and that device is ignored for %d s",
                req.device, source[0], SIGNATURE_BACKOFF_S,
            )
            return

        if now - self._started < STARTING_S:                           # 5. starting
            self._refuse(req, "starting", addr, now)
            return

        wall = self._wall_ms()                                         # 6. the clock
        last = self._last_t.get(req.device)
        if abs(wall - req.t) > CLOCK_WINDOW_MS or (last is not None and req.t <= last):
            self._refuse(req, "clock", addr, now)
            return

        if req.entity not in record.shared:                            # 7. shared
            self._refuse(req, "not_shared", addr, now)
            return

        if req.entity not in record.control:                           # 8. on this device's list
            self._refuse(req, "not_on_list", addr, now)
            return

        kind = req.entity.split(".", 1)[0]                             # 9. the action fits
        if service_for(kind, req.action) is None:
            self._refuse(req, "action", addr, now)
            return

        self._last_t[req.device] = req.t                               # 10. take it
        taken = self._answer("taken", req, limit_ms=self._limit_ms)
        self._remember(req, taken, now)
        self._send(taken, addr)

        try:
            outcome, detail = await self._act(req.entity, kind, req.action, self._limit_ms / 1000)
        except Exception as err:  # noqa: BLE001
            outcome, detail = "not_changed", f"error: {err}"
        if outcome not in OUTCOMES:
            outcome, detail = "not_changed", f"no outcome ({outcome})"

        result = self._answer("result", req, outcome=outcome)
        kept = self._memory.get(req.id)
        if kept is not None and kept.request == req.raw:
            kept.answer = result
        self._log.info(
            "home control: %s asked %s %s: %s (%s)", req.device, req.action, req.entity, outcome, detail
        )

        sent_at = 0
        for at_ms in RESULT_SENDS_MS:
            if at_ms > sent_at:
                await self._sleep((at_ms - sent_at) / 1000)
                sent_at = at_ms
            self._send(result, addr)
