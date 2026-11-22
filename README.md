# Intelleta for Home Assistant

Brings your Intelleta devices into Home Assistant, and lets Andy switch the
things you share from it.

Needs Home Assistant 2024.11 or later, and HACS, the Home Assistant Community
Store.

## Install it

Follow the install guide: [docs/installing.md](docs/installing.md). In short:
install Intelleta from HACS, make a key in the Intelleta app (**Settings → Home
Assistant → Make a key**), paste it into Home Assistant, then choose what Andy
can control.

## Your readings

Each device on your account appears in Home Assistant with the readings it
measures, read over your own network.

Controls (volume, brightness, screen, brightness mode) need the internet.

## Voice control

1. In Home Assistant, go to **Settings → Devices & services → Intelleta** and
   press **Configure**. Choose the things to share with Intelleta.
2. In the Intelleta app, open a device, go to **Voice control**, and pick up to
   six of them.
3. Say "Hi Andy, turn on" and the name.

Andy can turn things on and off, open and close them, lock and unlock them, and
start scenes.

Your devices must reach Home Assistant on UDP port 41846 on your home network.

The names, kinds and rooms of the things you share are sent to your Intelleta
account, and to Google, which runs Andy's voice, so Andy can recognise them.

## If your internet goes down

Readings keep coming. Voice control and controls need the internet.

## Something not working?

The install guide has a troubleshooting table:
[docs/installing.md](docs/installing.md#troubleshooting).

## Licence

Apache 2.0.

Home Assistant is a trademark of the Open Home Foundation. This project is not
affiliated with or endorsed by the Open Home Foundation.
