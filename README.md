# Intelleta for Home Assistant

Brings Intelleta air-sensing devices into Home Assistant.

> **⚠ Scaffold.** The repository and its gates exist (card 87). It does not yet
> do anything useful — sign-in and readings arrive with card 88. It is private
> until launch, deliberately.

## How it will work

Readings come **from the cube over your own network**, so they keep arriving
when your broadband does not. Our cloud is the fallback, not the path.

You sign in once with your Intelleta account. That is required before anything
works — a deliberate decision, taken knowing it costs a smoother first run.

## What this repository is not

⛔ **It does not contain the device's wire protocol, and never will.** It talks
to our API and to the cube's own local endpoint. Copying the device contract in
would publish the protocol when this goes public, and would tie software living
in customers' homes to a contract it cannot be upgraded alongside. There is a
test that fails if anyone tries.

## Installing it

The customer path — how somebody gets from "I have a cube" to "it is in my Home
Assistant", what they type, and what every failure along the way should say — is
written down in [docs/installing.md](docs/installing.md).

⚠ It was written **before** the code rather than after, because the alternative
is inventing it at release under time pressure.

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
