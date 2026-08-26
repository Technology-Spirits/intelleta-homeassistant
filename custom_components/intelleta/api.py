"""Talking to our cloud, and to a cube on the customer's own network. Card 88.

Two clients, deliberately in one file because they are two halves of one idea:

  * `CloudClient`  — the account. Which cubes exist, who they belong to, what
                     they are called. The AUTHORITY (card 93).
  * `LocalClient`  — one cube, over the home network. The readings themselves.

⛔ ONLY THE CLOUD CLIENT CARRIES THE CREDENTIAL. The local endpoint is on the
customer's own network and is not authenticated, by ruling — so nothing secret
may ever be sent to it. Sending our key to an address something on the wifi
announced would hand it to whatever was listening.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import aiohttp

_LOGGER = logging.getLogger(__name__)

# ⚠ SHORT ON PURPOSE. The cube is on the same network; if it has not answered in
# a couple of seconds it is not going to, and a long timeout would hold the
# poll open and delay the fallback decision (card 95) rather than help.
LOCAL_TIMEOUT_S = 4

# Longer, because this one crosses the internet — but still bounded, because a
# hung setup screen is worse than a failed one.
CLOUD_TIMEOUT_S = 15


class AuthFailed(Exception):
    """The key was refused. Revoked, mistyped, or never ours.

    ⛔ DISTINCT FROM AN OUTAGE ON PURPOSE. Home Assistant reacts differently:
    this asks the customer to fix something, an outage retries quietly. Merging
    them would either nag people about a network blip or silently stop working
    after a revoke — and the second is the one that generates "it just stopped".
    """


class CloudUnavailable(Exception):
    """Our cloud could not be reached or did not answer sensibly. Retryable."""


@dataclass(frozen=True)
class CloudDevice:
    """One cube as the ACCOUNT describes it. The authority for card 93."""

    device_id: str
    name: str
    capabilities: tuple[str, ...]
    device_type: str = "aqm-cube"
    firmware_version: str | None = None
    last_seen: int = 0

    def as_dict(self) -> dict:
        """The shape `matching.reconcile` expects — it takes plain dicts so it
        can stay free of every import, including this one."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "capabilities": list(self.capabilities),
        }


class CloudClient:
    """The account side. Authenticated with the key the customer minted."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, key: str) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._key = key

    async def async_list_devices(self) -> list[CloudDevice]:
        """Which cubes this account owns.

        Doubles as the sign-in check: it is the cheapest call that proves the
        key works, so the config flow uses it rather than a dedicated "validate"
        endpoint that could drift away from what the integration actually does.
        """
        try:
            async with self._session.get(
                f"{self._base}/integration/devices",
                # ⛔ THE HEADER, NEVER THE QUERY STRING. Query strings end up in
                # server logs; this is exactly the reasoning that put the live
                # socket's credential behind a single-use pass.
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=aiohttp.ClientTimeout(total=CLOUD_TIMEOUT_S),
            ) as response:
                if response.status in (401, 403):
                    raise AuthFailed("the key was refused")
                if response.status >= 400:
                    raise CloudUnavailable(f"cloud answered {response.status}")
                body = await response.json()
        except AuthFailed:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            # ⚠ ValueError covers a body that is not JSON — a captive portal or
            # a proxy error page, which is a real thing on customer networks and
            # must read as "cloud unavailable" rather than as a crash.
            raise CloudUnavailable(str(err)) from err

        return [
            device
            for device in (_parse_device(raw) for raw in (body or {}).get("devices", []))
            if device is not None
        ]


class LocalClient:
    """One cube, on the customer's own network.

    ⛔ NO CREDENTIAL EVER GOES HERE. See the module note.
    """

    def __init__(self, session: aiohttp.ClientSession, address: str) -> None:
        self._session = session
        self._address = address

    async def async_readings(self) -> dict | None:
        """The cube's latest payload, or None if it could not be reached.

        ⚠ RETURNS None RATHER THAN RAISING for an unreachable cube, because
        unreachable is an ORDINARY condition here, not an error: it is what the
        fallback policy exists to handle, and raising would make the normal path
        an exception path.
        """
        url = f"http://{self._address}/readings"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=LOCAL_TIMEOUT_S)
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("local endpoint at %s answered %s", self._address, response.status)
                    return None
                # ⚠ content_type=None because a small embedded server may not
                # send a JSON content type, and refusing a perfectly good body
                # over a header would be a silly way to lose the local path.
                return await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.debug("local endpoint at %s unreachable: %s", self._address, err)
            return None


def _parse_device(raw: object) -> CloudDevice | None:
    """One entry from the account list, or None if it is unusable.

    ⚠ A malformed entry is SKIPPED, not fatal. One bad row must not cost the
    customer every other cube they own.
    """
    if not isinstance(raw, dict):
        return None
    device_id = raw.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        return None

    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        name = device_id

    firmware = raw.get("firmware_version")
    if not isinstance(firmware, str) or not firmware.strip():
        firmware = None

    last_seen = raw.get("last_seen")
    if isinstance(last_seen, bool) or not isinstance(last_seen, int):
        last_seen = 0

    return CloudDevice(
        device_id=device_id.strip(),
        name=name.strip(),
        capabilities=tuple(c for c in capabilities if isinstance(c, str)),
        device_type=raw.get("device_type") if isinstance(raw.get("device_type"), str) else "aqm-cube",
        firmware_version=firmware,
        last_seen=last_seen,
    )
