# Release notes

The text under each heading is pasted into that version's GitHub release. The
heading is the release's tag and matches `version` in `manifest.json`. Newest
first. The text is a draft until it has been through the words review described
in `maintaining.md`.

## v0.3.3

Corrects 0.3.2. Straight after you pick a thing for a device in the Intelleta
app, Andy could say Home Assistant had not answered while the thing was
switched a moment later. Now the first request in that moment is answered in
time: if Home Assistant cannot confirm the new pick quickly enough, Andy says
it cannot control that one, nothing is switched, and asking again works.

After updating, restart Home Assistant.

## v0.3.2

A thing you have just picked for a device in the Intelleta app can be asked
for straight away. Before, Home Assistant could turn the request away for up
to a minute after the pick.

After updating, restart Home Assistant.

## v0.3.1

Scenes now have their own list, and you can share a whole device from Home
Assistant, such as a wall switch with four lights, as one thing that Andy
switches all at once.

- **Three lists on Share with Intelleta.** Press **Configure** on the Intelleta
  entry in Home Assistant: **Single things**, **Scenes**, and **Whole devices
  from Home Assistant**. What you shared before is still shared.
- **A whole device counts as one.** In the Intelleta app it is one of the six
  you can pick on an Intelleta device. Say "Hi Andy, turn on" and its name.

After updating, restart Home Assistant.

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
