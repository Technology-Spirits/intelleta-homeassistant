# Release notes

The text under each heading is pasted into that version's GitHub release. The
heading is the release's tag and matches `version` in `manifest.json`. Newest
first. The text is a draft until it has been through the words review described
in `maintaining.md`.

## v0.3.0

Andy can now control things you share from Home Assistant.

- **Share with Intelleta.** Press **Configure** on the Intelleta entry in Home
  Assistant and choose the lights, switches, scenes and other things to share.
  Their names, kinds and rooms are sent to your Intelleta account, which also
  keeps where Home Assistant is on your home network.
- **Voice control.** In the Intelleta app, open a device, go to **Voice
  control**, and pick up to six of the things you shared. Then say "Hi Andy,
  turn on" and the name.
- **On your own network.** A device asks Home Assistant directly over your home
  Wi-Fi, and Home Assistant decides. Your devices must reach Home Assistant on
  UDP port 41846.
- **A new place for the key.** The key now comes from **Settings → Home
  Assistant → Make a key** in the Intelleta app. Making a new key stops the old
  one working.

After updating, restart Home Assistant. The install guide has the full steps
and a troubleshooting table: `docs/installing.md`.
