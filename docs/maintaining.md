# Maintaining this integration

Notes for whoever releases it. Customers read `installing.md`; this file is for us.

## Versions

The version in `custom_components/intelleta/manifest.json` is what HACS offers as an
update. Raise it in the same change that alters behaviour, never afterwards.

A version we release is not a version anyone is running. This is software in other
people's homes, updated on their schedule. A fix is not live for a customer until they
have updated and restarted, so anything the cloud asks of a specific version must allow
for versions that cannot do it.

Every version gets a numbered GitHub release whose tag matches the manifest's
version. Without one, HACS shows the customer a commit hash instead of a version.
The release text is written beforehand in `release-notes.md`, under a heading
that is the tag; `tests/test_release_notes.py` fails if the manifest's version
has no notes there.

`hacs.json` names the oldest Home Assistant it runs on (`homeassistant`), so
HACS does not offer it to an older one. It is 2024.11: the "Share with
Intelleta" screen reads its entry the way Home Assistant provides it from that
version on. Raise it in the same change that starts using something newer.

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

Everything a customer reads goes through the words review: the install guide, the setup
screen, every error message in `strings.json`, and the name shown in Home Assistant's
integration list.

The Intelleta app opens `installing.md` from its "How to install it" link, so the
guide, the setup screen and the key messages must say what the app says.
`tests/test_install_guide_words.py` pins the guide's headings, its approved
sections and rows, and the three key messages word for word. The headings are
what links point at: rename one only on purpose, and change the test with it.

## What the customer shares, and the gate's key

**Configure** on the integration's entry opens the "Share with Intelleta" screen
(`config_flow.py`, the options step). It is three of Home Assistant's own pick
lists, several at once in each, and all three start empty:

- **Single things**: the entity picker, limited to lights, switches, fans, covers,
  locks, climate and media players (`sharing.SHAREABLE_KINDS` without scenes).
  Nothing inside those kinds is held back: the customer chooses.
- **Scenes**: the entity picker again, limited to scenes. Scenes are saved with
  the single things, as they always were; only the screen shows them apart.
- **Whole devices from Home Assistant**: the device picker, limited to devices
  that hold a light or a switch. A picked device is shared as ONE thing under the
  device's name. Its id is made by `sharing.whole_device_entity` from Home
  Assistant's id for the device, in the same form as an entity's id and always of
  kind `switch`, so the account, the app and an Intelleta device carry it like
  any other thing. Only this integration knows it stands for several: when a
  request for it arrives, `receiver.HassHome` turns it into the device's lights
  and switches as they are at that moment (`share.whole_members`: no settings or
  diagnostic toggles, nothing hidden or disabled, nothing of Intelleta's own),
  asks every one of them, and reports it changed only when all of them have
  (`sharing.whole_state`). What the gate allows and what the account is told are
  both built by `share.shared_ids`, so the two cannot differ.

What leaves the home, in `PUT /integration/shared` on the account (`share.py`,
`sharing.py`):

- for each picked thing: Home Assistant's id for it, its name as Home Assistant
  shows it, its kind (the id's domain) and its room (its own area, else its
  device's area, else none);
- the integration's version, read from the manifest;
- where a device reaches the integration on the home network: the address Home
  Assistant uses on it, the UDP port, and the public half of the integration's
  own key.

A device's own list (what was picked for it in the app) reaches this integration
with the readings' once-a-minute read of the account. A thing picked a moment ago
is on the device at once, so before the gate refuses a request as not on the
device's list it asks the account for the lists once more
(`gate.LIST_RECHECK_EVERY_S`, `coordinator.async_read_lists_again`): at most once
in five seconds for one device. A device waits 1,000 ms for its first answer, so
the gate answers within `gate.LIST_RECHECK_LIMIT_S` (0.6 s) whatever the account
does: refused if the look has not come back. A look that was too slow still
finishes, and the device's next request is judged against what it brought.

When it is sent: once at each start, when the screen is saved, and at the
once-a-minute check, but only if the body differs from the last one the account
accepted. An unchanged set is never sent again; `tests/test_sharing.py` proves
it. What the account answers decides the rest:

- an outage (no answer, or a 5xx): tried again at the next check;
- 404 or 405 (its side not deployed yet): not tried again until something
  changes, or an hour has passed, so a home does not cost a request a minute
  for nothing and still reaches the account once it has the route;
- 400 (it refuses this body): logged as a warning naming the field it gave, and
  not tried again until something changes;
- 401 or 403 (the key was refused): not tried again until something changes;
  the readings' poll asks the customer to sign in again, which starts the
  integration again with the new key.

Things the account would refuse outright (a bad id, an id over 255 bytes, an
empty or over-long name, text that is not well formed) are left out rather than
making it refuse the whole set. A thing it stores as not pickable (an id or a
name over 96 bytes, a name with a control character) is sent, so the app can
show it and say it cannot be picked.

Nothing is sent while the gate is not listening (below): the set carries the
address and port devices send their requests to.

The integration's key pair is RSA-2048, made once and kept in Home Assistant's
own storage (`.storage/intelleta.gate_key`, written private). The private half
never leaves Home Assistant. Removing the last Intelleta entry deletes it;
setting the integration up again makes a new one, which reaches the devices
through the account. The cryptography package ships with Home Assistant, so the
manifest's `requirements` stays empty.

## The gate: a device asks to switch a thing

An Intelleta device on the home network asks the integration to switch one
shared thing. The integration is the only thing that decides; the device's own
list is a convenience for the voice assistant, never the permission. Nothing
about an action passes through our cloud. The rules live in `gate.py` (no
Home Assistant imports, fully tested in `tests/`); `receiver.py` opens the
listener and is the door into Home Assistant's states and services.

The road. One UDP listener per Home Assistant, on port 41846 (the port sent to
the account with the shared set). A device sends one signed datagram, three
times; the integration answers to the request's source address, on port 41846.
If the port cannot be opened, the error is logged once, the port is tried again
every minute, and the shared set is not sent until it opens.

The four messages are compact JSON with a fixed field order and no whitespace
or escapes, at most 1280 bytes, and the signature always last:

    control  device -> gate   v, kind, from, t, id, entity, action, sig
    taken    gate -> device   v, kind, to, t, id, limit_ms, sig
    result   gate -> device   v, kind, to, t, id, outcome, sig
    refused  gate -> device   v, kind, to, t, id, why, sig

A request is read whole and rebuilt; if the rebuilt bytes differ from what
arrived (an extra field, a field out of order, a space, an escape), it is
dropped. Signatures are RSASSA-PSS with SHA-256, MGF1 SHA-256 and a 32-byte
salt, over the label `aqm-home-control/1`, a line feed, and the message up to
its signature field closed with `}`. The device signs with its own identity
key; the integration verifies it with the public key the account lists for
that device (`pubkey` on `GET /integration/devices`). The integration signs
its answers with its own key pair (the one whose public half goes to the
account with the shared set). `tests/home-control-vectors.json` holds signed
examples of each message and the public test keys they verify against.

The checks, in this order, stopping at the first that fails:

1. the shape above; else dropped;
2. a device the account lists with a usable key; else dropped (no key work);
3. a repeat: the last 32 requests are kept 60 seconds, each known by its
   device and its id, and the same bytes again get the same answer again,
   never a second action; the same id with other bytes is dropped. A request
   still being acted on is never pushed out, and a request refused for its
   clock is not kept, so recordings played back cannot push a real request out;
4. the signature; a failure is dropped, logged as a warning, and that device
   id is ignored for 10 seconds;
5. for the first 30 seconds after the gate starts: refused, `starting`;
6. the device's clock within 30 seconds of Home Assistant's, and later than
   its last request that was taken; else refused, `clock`;
7. the thing is shared on the "Share with Intelleta" screen; else refused,
   `not_shared`;
8. the thing is on the asking device's own list (`control` on
   `GET /integration/devices`); else refused, `not_on_list`;
9. the action fits the kind; else refused, `action`;
10. taken: the integration asks Home Assistant, watches the state, and
    answers `changed` or `not_changed`.

What each kind is asked, and when it counts as changed:

| Kind | Actions | Service | Changed when the state is |
|---|---|---|---|
| light, switch, fan | on / off | turn_on / turn_off | on / off |
| cover | open / close | open_cover / close_cover | open or opening / closed or closing |
| lock | lock / unlock | lock / unlock | locked or locking / unlocked or unlocking |
| climate | on / off | turn_on / turn_off | anything but off / off |
| media_player | on / off | turn_on / turn_off | anything but off or standby / off or standby |
| scene | run (or on) | turn_on | Home Assistant ran it |

A lock and a cover are never sent turn_on or turn_off: in Home Assistant's
generic road, off on a lock means unlock and on opens a cover. A thing already
in the asked state is changed at once, without a call. The integration watches
for `CONTROL_LIMIT_MS` (8 seconds, a placeholder until it is measured on a
bench); a thing that does not get there in time, is unavailable, or whose call
Home Assistant refuses is `not_changed`, and the log says which.

Every request that is answered gets one log line (at info, under
`custom_components.intelleta.gate`): the device, the action, the thing and the
answer. A failed signature is a warning.

Keys and lists come from the readings' own once-a-minute read of
`GET /integration/devices`. When the account cannot be reached, the last copy
read stands, so a request is still judged correctly with the internet down.
A device's list that is not a list of at most six different ids is held as
empty: that device switches nothing until the account sends one that reads
whole. When the account refuses the key, the gate holds no device of that
account until a poll succeeds again: the customer may have disconnected Home
Assistant on purpose. The account's copy is not kept across a restart of Home
Assistant yet.

A Home Assistant whose clock is wrong refuses every request with `clock`, and a
Home Assistant in a container that cannot hear UDP port 41846 never answers. In
a container without host networking the address reported to the account is the
container's own, which devices cannot reach, so publishing the port alone is
not enough: it needs host networking. The install guide's troubleshooting
table has a row for each, in approved words, pinned by
`tests/test_install_guide_words.py`.

## Tests that need a real Home Assistant

`tests_ha/` checks the share screen as Home Assistant builds it, the gate against
real states, services and a real UDP round trip on the machine, and the reading
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
