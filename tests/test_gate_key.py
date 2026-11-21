"""The gate's own key pair.

The integration makes an RSA-2048 key pair once, keeps it in Home Assistant's
own storage, and never sends the private half anywhere. Only the public half
leaves, as base64 of the DER SubjectPublicKeyInfo, the same form a device
receives it in.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from conftest import load
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

gate_key = load("gate_key")

VECTORS = json.loads(
    (Path(__file__).parent / "home-control-vectors.json").read_text(encoding="utf-8")
)


def test_a_new_key_is_rsa_2048_with_the_usual_exponent():
    private_pem = gate_key.new_private_key_pem()
    key = serialization.load_pem_private_key(private_pem.encode("ascii"), password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    assert key.key_size == 2048
    assert key.public_key().public_numbers().e == 65537


def test_every_new_key_is_a_different_key():
    assert gate_key.new_private_key_pem() != gate_key.new_private_key_pem()


def test_the_public_half_is_der_subject_public_key_info_in_base64():
    private_pem = gate_key.new_private_key_pem()
    public_b64 = gate_key.public_key_b64(private_pem)
    der = base64.b64decode(public_b64, validate=True)
    public = serialization.load_der_public_key(der)
    assert isinstance(public, rsa.RSAPublicKey)
    assert public.key_size == 2048
    assert len(public_b64) <= 392


def test_the_public_half_has_the_same_form_as_the_test_vectors_gate_key():
    """The device verifies with the form the contract's own vectors use."""
    public_b64 = gate_key.public_key_b64(gate_key.new_private_key_pem())
    reference = VECTORS["gate_pubkey"]
    assert len(public_b64) == len(reference)
    # Same DER header: the same algorithm identifier and the same layout.
    assert base64.b64decode(public_b64)[:32] == base64.b64decode(reference)[:32]


def test_the_public_half_never_carries_the_private_half():
    private_pem = gate_key.new_private_key_pem()
    public_b64 = gate_key.public_key_b64(private_pem)
    assert "PRIVATE" not in public_b64
    private_der = serialization.load_pem_private_key(
        private_pem.encode("ascii"), password=None
    ).private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    assert base64.b64encode(private_der).decode() not in public_b64


def test_a_stored_key_gives_the_same_public_half_every_time():
    private_pem = gate_key.new_private_key_pem()
    assert gate_key.public_key_b64(private_pem) == gate_key.public_key_b64(private_pem)


def test_a_stored_record_that_is_not_a_key_is_not_accepted():
    assert gate_key.valid_stored_key("not a key") is False
    assert gate_key.valid_stored_key(None) is False
    assert gate_key.valid_stored_key(gate_key.new_private_key_pem()) is True


def test_a_stored_key_is_read_once_for_both_halves():
    """Start-up reads the stored key once, off Home Assistant's loop, and gets
    the key to sign with and the public half to share from that one read."""
    pem = gate_key.new_private_key_pem()
    private, public = gate_key.usable_key_pair(pem)
    assert public == gate_key.public_key_b64(pem)
    assert private.private_numbers() == gate_key.load_private_key(pem).private_numbers()


def test_a_stored_key_that_cannot_be_used_reads_as_none():
    small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    small_pem = small.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    for stored in (None, 42, "", "not a key", small_pem):
        assert gate_key.usable_key_pair(stored) is None
