"""Does a bad key produce 'invalid_auth' rather than 'unknown'?

⛔ NOT A CI TEST, AND MUST NEVER BECOME ONE. It talks to the live API, so in CI
it would fail on our outages rather than on our bugs, and teach everybody to
ignore a red run. Run it by hand from inside a Home Assistant that has this
integration installed:

    cp scripts/live_auth_probe.py <ha-config>/
    docker exec <ha-container> python /config/live_auth_probe.py

It runs INSIDE the bench Home Assistant, against the LIVE deployed API. That is the
whole point: every unit test stubs the transport, so nothing until now has
proved that our real authorizer's refusal is mapped to the message that asks the
customer to mint a new key, rather than the one that tells them to read the log.
"""
import asyncio, sys
sys.path.insert(0, "/config/custom_components")

import aiohttp
from intelleta.api import CloudClient, AuthFailed, CloudUnavailable
from intelleta.const import API_BASE_URL


async def main() -> int:
    failures = []
    async with aiohttp.ClientSession() as session:
        for name, key in (
            ("a garbage key", "intelleta_" + "z" * 43),
            ("an empty key", ""),
            ("a key from another scheme", "Bearer abc123"),
        ):
            try:
                await CloudClient(session, API_BASE_URL, key).async_list_devices()
            except AuthFailed:
                print(f"  PASS  {name}: refused as AuthFailed -> 'invalid_auth'")
            except CloudUnavailable as e:
                print(f"  FAIL  {name}: reported as an OUTAGE ({e}). The customer "
                      f"would be told to wait for a fault that is theirs to fix.")
                failures.append(name)
            except Exception as e:
                print(f"  FAIL  {name}: {type(e).__name__} -> 'unknown'. The "
                      f"customer gets 'read the log' instead of 'mint a new key'. {e}")
                failures.append(name)
            else:
                print(f"  FAIL  {name}: ACCEPTED BY THE LIVE API. This is a hole.")
                failures.append(name)
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
