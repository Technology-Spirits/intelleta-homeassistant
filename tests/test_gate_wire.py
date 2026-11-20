"""The four home-control messages on the wire: their canonical form, and the
signatures that prove who sent them.

The vectors file holds one signed message of each kind, made with throw-away
keys whose private halves no longer exist. So it can prove the gate reads and
verifies exactly what a device sends, and builds its answers byte for byte the
way a device expects them. Signing itself is tested with keys made here.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from conftest import load
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

gate = load("gate")

VECTORS = json.loads(
    (Path(__file__).resolve().parent / "home-control-vectors.json").read_text(encoding="utf-8")
)
WIRES = {m["name"]: m["wire"].encode("utf-8") for m in VECTORS["messages"]}
DEVICE_KEY = gate.load_public_key(VECTORS["device_pubkey"])
GATE_PUBLIC = gate.load_public_key(VECTORS["gate_pubkey"])


def _fields(wire: bytes) -> dict:
    return json.loads(wire)


# ── every vector, as its file says ──────────────────────────────────────────


def test_every_vector_is_accepted_or_refused_as_its_file_says():
    """The gate accepts `control` against the device key and refuses the
    altered one; the three answers verify against the gate key and the one
    signed by the wrong key does not."""
    assert VECTORS["label"] == gate.LABEL.decode("ascii")

    control = gate.parse_control(WIRES["control"])
    assert control is not None
    assert gate.verify(DEVICE_KEY, control.signed, control.sig)

    altered = gate.parse_control(VECTORS["refuse_signature"].encode("utf-8"))
    assert altered is not None, "it is well formed; only its signature is wrong"
    assert not gate.verify(DEVICE_KEY, altered.signed, altered.sig)

    for name in ("taken", "result", "refused"):
        signed, sig = gate.split_signed(WIRES[name])
        assert gate.verify(GATE_PUBLIC, signed, sig), name
        # A gate never takes an answer as a request.
        assert gate.parse_control(WIRES[name]) is None, name

    signed, sig = gate.split_signed(VECTORS["refuse_wrong_signer"].encode("utf-8"))
    assert not gate.verify(GATE_PUBLIC, signed, sig)


def test_the_control_vector_reads_as_the_device_meant_it():
    control = gate.parse_control(WIRES["control"])
    assert control.device == VECTORS["device_id"]
    assert control.t == 1763658000000
    assert control.id == "000102030405060708090a0b0c0d0e0f"
    assert control.entity == "light.living_lamp"
    assert control.action == "on"
    assert control.raw == WIRES["control"]


@pytest.mark.parametrize("name", ["taken", "result", "refused"])
def test_the_gate_builds_each_answer_exactly_as_the_vector_reads(name):
    """The bytes the gate signs for an answer are the vector's own bytes up to
    the signature, so a device's canonical check passes on them."""
    fields = _fields(WIRES[name])
    extra = {k: fields[k] for k in ("limit_ms", "outcome", "why") if k in fields}
    body = gate.answer_body(name, to=fields["to"], t=fields["t"], id=fields["id"], **extra)
    signed, _sig = gate.split_signed(WIRES[name])
    assert gate.LABEL + body == signed


def test_an_answer_the_gate_signs_verifies_with_its_public_half():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_b64 = base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode("ascii")
    wire = gate.sign_answer(
        private, "result", to=VECTORS["device_id"], t=1763658000900,
        id="000102030405060708090a0b0c0d0e0f", outcome="changed",
    )
    signed, sig = gate.split_signed(wire)
    assert len(sig) == 256
    assert gate.verify(gate.load_public_key(public_b64), signed, sig)
    assert len(wire) == len(WIRES["result"]), "same fields, same size"


def test_the_largest_legal_messages_are_the_sizes_the_contract_gives():
    sizes = VECTORS["largest_legal_sizes"]
    sig = b"A" * 344
    control = (
        gate.control_body(device="aqm-" + "F" * 12, t=9_999_999_999_999, id="f" * 32,
                          entity="a" * 47 + "." + "b" * 48, action="unlock")
    )
    assert len(gate.with_sig(control, sig)) == sizes["control"]
    common = {"to": "aqm-" + "F" * 12, "t": 9_999_999_999_999, "id": "f" * 32}
    assert len(gate.with_sig(gate.answer_body("taken", limit_ms=30000, **common), sig)) == sizes["taken"]
    assert len(gate.with_sig(gate.answer_body("result", outcome="not_changed", **common), sig)) == sizes["result"]
    assert len(gate.with_sig(gate.answer_body("refused", why="not_on_list", **common), sig)) == sizes["refused"]


# ── read, then refuse; never clip ───────────────────────────────────────────

GOOD = WIRES["control"].decode("utf-8")


@pytest.mark.parametrize(
    "wire",
    [
        GOOD.replace('{"v":1,', '{ "v":1,'),                         # whitespace
        GOOD.replace('"v":1', '"v":2'),                              # another version
        GOOD.replace('"v":1', '"v":1.0'),                            # not an integer
        GOOD.replace('"v":1', '"v":true'),                           # a boolean
        GOOD.replace('"kind":"control"', '"kind":"taken"'),          # not a request
        GOOD.replace('"from":"aqm-A1B2', '"from":"aqm-a1b2'),        # lowercase id
        GOOD.replace('"t":1763658000000', '"t":176365800000'),       # 12 digits
        GOOD.replace('"t":1763658000000', '"t":"1763658000000"'),    # a string
        GOOD.replace('"id":"0001', '"id":"000G'),                    # not hex
        GOOD.replace('"entity":"light.living_lamp"', '"entity":"Light.living_lamp"'),
        GOOD.replace('"entity":"light.living_lamp"', '"entity":"light.living\\u005flamp"'),  # an escape
        GOOD.replace('"entity":"light.living_lamp"', '"entity":"l.' + "a" * 95 + '"'),     # 97 bytes
        GOOD.replace('"action":"on"', '"action":"toggle"'),
        GOOD.replace('"action":"on",', '"action":"on","extra":1,'),  # a field the table lacks
        GOOD.replace('"entity":"light.living_lamp",', ""),           # a field missing
        GOOD.replace('"from":"aqm-A1B2C3D4E5F6","t":1763658000000',
                     '"t":1763658000000,"from":"aqm-A1B2C3D4E5F6"'),  # wrong order
        GOOD.replace('"sig":"Lkh', '"sig":"Lk'),                     # 343 characters
        GOOD[:-1] + "}\n",                                           # a trailing byte
    ],
)
def test_a_message_out_of_shape_is_dropped(wire):
    assert gate.parse_control(wire.encode("utf-8")) is None


def test_a_datagram_over_1280_bytes_is_dropped_unread():
    assert gate.parse_control(WIRES["control"] + b" " * (1281 - len(WIRES["control"]))) is None


def test_a_datagram_that_is_not_utf8_or_not_json_is_dropped():
    assert gate.parse_control(b"\xff\xfe") is None
    assert gate.parse_control(b"not json") is None
    assert gate.parse_control(b"[]") is None
    assert gate.parse_control(b"") is None


def test_a_field_given_twice_is_dropped():
    doubled = GOOD.replace('"action":"on"', '"action":"on","action":"on"')
    assert gate.parse_control(doubled.encode("utf-8")) is None


@pytest.mark.parametrize(
    "pubkey",
    [None, "", "<base64 SubjectPublicKeyInfo of the device's identity key, or null>",
     "A" * 393, base64.b64encode(b"not a key").decode("ascii")],
)
def test_something_that_is_not_an_rsa_key_holds_no_key(pubkey):
    assert gate.load_public_key(pubkey) is None


def test_an_rsa_key_of_another_size_holds_no_key():
    small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    b64 = base64.b64encode(
        small.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    ).decode("ascii")
    assert gate.load_public_key(b64) is None
