"""The integration's own key pair.

A device that asks this integration to switch a thing needs to know the
answer really came from here. So the integration makes an RSA-2048 key pair
once, keeps it in Home Assistant's own storage, and signs its answers with it.

⛔ THE PRIVATE HALF NEVER LEAVES HOME ASSISTANT. Only the public half is sent,
to the account, which passes it to the customer's devices. It is sent as
base64 of the DER SubjectPublicKeyInfo (exponent 65537, 392 characters), the
form a device already reads keys in.

The cryptography package ships with Home Assistant, so it is not a manifest
requirement. This module imports nothing of Home Assistant's, so it is tested
on any machine; keeping the key in storage is `share.py`'s job.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_BITS = 2048
PUBLIC_EXPONENT = 65537


def new_private_key_pem() -> str:
    """A fresh key pair, as unencrypted PKCS#8 PEM text for storage.

    ⚠ SLOW (tens to hundreds of milliseconds). Call it off Home Assistant's
    event loop.
    """
    key = rsa.generate_private_key(public_exponent=PUBLIC_EXPONENT, key_size=KEY_BITS)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def load_private_key(private_pem: str) -> rsa.RSAPrivateKey:
    """The key in `private_pem`; ValueError unless it is an RSA-2048 key.

    ⚠ SLOW on a small computer (the key is checked as it is read). Call it off
    Home Assistant's event loop.
    """
    key = serialization.load_pem_private_key(private_pem.encode("ascii"), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != KEY_BITS:
        raise ValueError("not an RSA-2048 key")
    return key


def _public_b64(key: rsa.RSAPrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode("ascii")


def usable_key_pair(private_pem: object) -> tuple[rsa.RSAPrivateKey, str] | None:
    """What storage gave back, read once: the key to sign with and its public
    half (base64 of the DER SubjectPublicKeyInfo), or None when it is not a
    key this integration can use. ⚠ Slow: call it off the event loop."""
    if not isinstance(private_pem, str):
        return None
    try:
        key = load_private_key(private_pem)
    except (ValueError, TypeError):
        return None
    return key, _public_b64(key)


def valid_stored_key(private_pem: object) -> bool:
    """Whether what storage gave back is a key this integration can use."""
    return usable_key_pair(private_pem) is not None


def public_key_b64(private_pem: str) -> str:
    """The public half, base64 of the DER SubjectPublicKeyInfo."""
    return _public_b64(load_private_key(private_pem))
