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
