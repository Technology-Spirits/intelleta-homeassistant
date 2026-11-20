# Maintaining this integration

Notes for whoever releases it. Customers read `installing.md`; this file is for us.

## Versions

The version in `custom_components/intelleta/manifest.json` is what HACS offers as an
update. Raise it in the same change that alters behaviour, never afterwards.

A version we release is not a version anyone is running. This is software in other
people's homes, updated on their schedule. A fix is not live for a customer until they
have updated and restarted, so anything the cloud asks of a specific version must allow
for versions that cannot do it.

## The two-second red check

Continuous integration can fail without running: a job that fails in about two seconds
having executed zero steps did not test anything. It means GitHub Actions did not start
the job, usually a billing limit. Open the annotation on the check before reading the code.

## What arms itself now that the repository is public

- HACS's own validation in CI. It reads the repository through GitHub's public API and
  could see nothing while the repository was private.
- Discoverability.

The logo does not arm itself. It lives in Home Assistant's brands project and is reviewed
by their maintainers on their own timetable. The prepared files are in `brands/`.

## Words

Everything a customer reads goes through Raye and Thomas: the install guide, the setup
screen, every error message in `strings.json`, and the name shown in Home Assistant's
integration list.

## What the customer shares, and the gate's key

**Configure** on the integration's entry opens the "Share with Intelleta" screen
(`config_flow.py`, the options step). It is Home Assistant's own entity picker,
several at once, limited to lights, switches, fans, covers, locks, climate, media
players and scenes (`sharing.SHAREABLE_KINDS`). It starts empty. Nothing inside
those kinds is held back: the customer chooses.

What leaves the home, in `PUT /integration/shared` on the account (`share.py`,
`sharing.py`):

- for each picked thing: Home Assistant's id for it, its name as Home Assistant
  shows it, its kind (the id's domain) and its room (its own area, else its
  device's area, else none);
- the integration's version, read from the manifest;
- where a device reaches the integration on the home network: the address Home
  Assistant uses on it, the UDP port, and the public half of the integration's
  own key.

When it is sent: once at each start, when the screen is saved, and at the
once-a-minute check, but only if the body differs from the last one the account
accepted. An unchanged set is never sent again; `tests/test_sharing.py` proves
it. A failed send is tried at the next check. If the account answers 404 (its
side not deployed yet) that body is not retried until something changes, so a
home does not cost a request a minute for nothing. Things the account would
refuse (a bad id, an empty or over-long name) are left out rather than making it
refuse the whole set.

The integration's key pair is RSA-2048, made once and kept in Home Assistant's
own storage (`.storage/intelleta.gate_key`, written private). The private half
never leaves Home Assistant. Removing the last Intelleta entry deletes it;
setting the integration up again makes a new one, which reaches the devices
through the account. The cryptography package ships with Home Assistant, so the
manifest's `requirements` stays empty.

## Tests that need a real Home Assistant

`tests_ha/` checks the share screen as Home Assistant builds it and the reading
of names and rooms from its registries. Home Assistant's test harness does not
run on Windows and is not installed in CI, so run these on Linux. One way that
works is Home Assistant's own image (it has the compiled packages the harness
needs; a slim Python image has no compiler and fails to install it). Pick the
harness release that matches an available Home Assistant version:

    docker run --rm -v "$PWD:/src" -w /src --entrypoint sh \
      ghcr.io/home-assistant/home-assistant:<version> -c \
      "uv pip install --system --index-strategy unsafe-best-match \
         pytest-homeassistant-custom-component homeassistant==<matching version> && \
       python3 -m pytest tests_ha -q -p no:cacheprovider -o asyncio_mode=auto"

Measured on 2026-11-20 with the 2026.8.3 image, Home Assistant 2026.8.2 and
harness 0.13.356.
