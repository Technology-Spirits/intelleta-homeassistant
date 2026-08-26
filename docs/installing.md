# From "I have a cube" to "it is in my Home Assistant"

Card 96. Written down **before** release rather than invented at release under
time pressure, which is the only reason this file exists ahead of the code.

---

## The path, end to end

### 1. They learn it exists

Three places, and the order matters because only the first two are ours to
control:

- **In the portal**, on the screen that mints the key — Settings → Account → Home Assistant. Somebody
  who is already looking for this is the easiest person to help.
- **In the box**, one line. Not instructions — just that it exists.
- **In Home Assistant's own installer listing**, once the repository is public.
  This is the one that brings people who were not looking for us.

### 2. They add it to Home Assistant

Until the repository is public, this is a manual copy of
`custom_components/intelleta/` into their configuration directory, then a
restart. That is fine for us and for a handful of testers, and unacceptable as a
shipping answer — which is what step 5 is about.

Once public: add as a custom repository in the installer, install, restart.

### 3. They type one thing, once

**An Intelleta key**, minted in the portal under Settings → Account → Home Assistant, pasted into the
integration's setup screen.

⚠ **The key is shown once, at the moment it is created, and never again.** We
keep only a one-way fingerprint of it, so "show me my key again" is not refused,
it is impossible. Somebody who closes the page without copying it mints another
— which costs them ten seconds, and is the whole reason a stolen backup of our
database does not hand anybody a working key.

⛔ **They never type a Home Assistant token, and there is nowhere to put one.**
Our integration runs inside Home Assistant, where being inside *is* the
permission. The only credential in the whole story is ours, and it is revocable
from the portal in one tap.

⛔ **They never type a cube's address.** The cube announces itself. If it does
not, the answer is the diagnostic in step 5, not a text box — a text box here
would be a permanent tax on everybody to work around a fault that affects a few.

⚠ **Sign-in is required before anything works.** Owner ruling 2026-08-25, taken
knowing it costs a smoother first run, in exchange for always knowing who our
customers are.

### 4. What they see when it works

Their cubes appear as Home Assistant devices, named as they named them in the
portal, with the readings that cube actually has — and nothing else. A cube that
measures only carbon dioxide shows carbon dioxide, not five sensors reading
"unavailable" forever.

Readings arrive from the cube over their own network, so they keep arriving with
the broadband unplugged.

### 5. What they see when it does not

Every one of these must say something a person can act on. "Unknown error" is
not an answer; neither is a stack trace.

| What went wrong | What we say |
|---|---|
| Key rejected | That the key was not accepted, and where to mint a new one — by name, Settings → Account → Home Assistant, not "in the portal" |
| Key revoked later | That it was revoked, and that a new one is needed — **not** a silent stop |
| Account has no cubes | That the account is fine and has nothing claimed yet, with where to claim |
| Cube owned but not found on the network | That we can see it on the account but not on this network — **and that readings will come from the internet meanwhile**, so this is a degradation, not a failure |
| Something announcing itself that is not on the account | Nothing at all to the customer. It is a neighbour's cube. It belongs in diagnostics, not in a notification |
| No internet at all during setup | That setup needs the internet once, even though running does not |

⚠ **The fourth row is the one most likely to be got wrong.** It is tempting to
report it as an error. It is not an error — it is the fallback working. Reported
as a failure, it generates support conversations about a system behaving
correctly.

---

## Release

### Going public is a deliberate step

⛔ Owner ruling 2026-08-25: **company account, private while we build, public at
launch.** Home Assistant's installer requires public — but not before we are
ready.

Two things happen automatically the moment it flips, and both are wanted:

- The installer's own validation, which is **skipped while private** because it
  reads the repository through GitHub's public API and can see nothing. It arms
  itself; nobody has to remember.
- The repository becomes discoverable, which is the point.

One thing does **not** happen automatically: the logo. It lives in Home
Assistant's own project and is reviewed by their maintainers on their timetable
— which is why it is card 94 and why it should be started early rather than
discovered late.

### Versioning, and reaching somebody who already installed it

The version in the manifest is what the installer offers as an update. Bump it
in the same change that alters behaviour, never afterwards.

⛔ **A version we release is not a version anyone is running.** This is software
in customers' homes, updated on their schedule. The energy product learned this
expensively: a fix shipped and then sat unrunning until each customer updated and
restarted, so the bug it fixed was still live for everybody who had not.

Consequences we should design for rather than discover:

- The integration reports its own version to us, so we know what is actually out
  there rather than what we published.
- Anything the cloud asks a specific version to do must account for versions
  that cannot do it.

---

## ⛔ The two-second red check

Continuous integration silently does not run when GitHub billing is unhappy.
**A check that fails in two seconds having executed zero steps is a bill, not a
test failure.**

It has happened on the personal account and on the organisation. Anyone
releasing from here should know it before they see it, not after an afternoon
spent on the code.

---

## Naming

The technical identifier `intelleta` is settled — it is the company name.

⚠ **Everything a customer reads goes through Raye and Thomas**: the installation
instructions, the setup screen, every error message in the table above, and the
name shown in Home Assistant's integration list. Draft, then hand over. The
placeholders live in `strings.json` so that is a find-and-replace rather than
archaeology.
