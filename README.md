# Intelleta for Home Assistant

Brings Intelleta air-sensing devices into Home Assistant.

## How it works

You sign in once with a key from your Intelleta account. Your devices then appear
in Home Assistant with the readings each one measures. Readings arrive through
your Intelleta account; reading a device directly over your own network is
designed, and not yet live.

## What this repository is not

⛔ **It does not contain the device's wire protocol, and never will.** It talks
to our API and to the device's own local endpoint. Copying the device contract in
would publish the protocol, and would tie software living in customers' homes to
a contract it cannot be upgraded alongside. There is a test that fails if anyone
tries.

## Installing it

[docs/installing.md](docs/installing.md). Notes for whoever releases it are in
[docs/maintaining.md](docs/maintaining.md).

## Development

```sh
pip install -r requirements-test.txt
pytest tests/ -v
```

### ⛔ Home Assistant's test harness does not run on Windows

Measured 2026-08-26. `pytest-homeassistant-custom-component` imports
`homeassistant.runner`, which imports `fcntl` — POSIX only. Installing it on a
Windows machine breaks test collection entirely, including for tests that have
nothing to do with Home Assistant.

`homeassistant.core` itself imports fine on Windows; it is specifically the
harness that does not.

So the split is deliberate:

- **Logic modules import nothing** and are tested here, on any machine, in under
  a second. That is most of the rules worth pinning — matching, the fallback
  policy, capability gating, parsing.
- **Anything that genuinely needs Home Assistant** is verified against a real
  one: the bench instance in `bench-ha/`, or CI, which runs on Linux.

⚠ Do not add the harness to `requirements-test.txt` to "fix" a Windows machine.
It will fix nothing and break the fast suite for everybody.

Three gates run on every push, and two of them are not ours: Home Assistant's
own manifest validator and the installer's. They also run weekly, because they
enforce rules that change when *their* projects change rather than when ours
does.

## Naming

The technical identifier `intelleta` is settled — it is the company name.
**Every customer-visible string goes through Raye and Thomas.** Placeholders
live in `strings.json` where they are easy to find and replace.

## Licence

Apache 2.0.

Home Assistant is a trademark of the Open Home Foundation. This project is not
affiliated with or endorsed by the Open Home Foundation.
