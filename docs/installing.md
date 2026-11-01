# Installing Intelleta in Home Assistant

You need Home Assistant with HACS, an Intelleta account with at least one device, and an internet connection during setup. After setup, Home Assistant reads each device over your own network, so readings keep coming if the internet goes down, with one exception, under [If your internet goes down](#if-your-internet-goes-down).

## 1. Add the integration

In HACS, open **Integrations**, then **Custom repositories** from the three-dot menu. Paste `https://github.com/Technology-Spirits/intelleta-homeassistant`, choose **Integration**, and press **Add**. Download **Intelleta**, then restart Home Assistant.

## 2. Mint a key

In the Intelleta app, go to **Account → Integration keys → Mint a key**. When it asks what will use the key, type a name such as Home Assistant.

Copy the key immediately: it is shown once and never again. If you lose it, mint another and revoke the old one in the same place.

## 3. Connect

In Home Assistant, go to **Settings → Devices & services → Add integration**, choose **Intelleta**, and paste the key.

## What you get

Each device on your account appears in Home Assistant with exactly the readings it measures, read from the device itself over your own network. Your account tells Home Assistant where each device is, so you type no address.

Each entity carries two attributes. `source` is `local` when the value came from the device over your network, and `cloud` when it came through your Intelleta account because the device could not be reached on your network. `cloud_reachable` says whether your account answered on the last check.

Controls (volume, brightness, screen, brightness mode) show the value the device itself reports. Changing one goes through your Intelleta account and needs the internet. That is deliberate: on your network, the device gives out readings and takes no commands.

## If your internet goes down

Readings keep coming. Home Assistant goes on reading each device over your network and checks your account again when the internet returns.

Until then, controls cannot be changed. A change you make is not applied, and the control keeps showing what the device last reported.

If Home Assistant starts or restarts while the internet is down, everything is unavailable until the internet returns. It learns your devices from your account each time it starts, and your account is out of reach. When the internet returns, it recovers on its own.

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| The key was not accepted | Part of it was missed when copying, or it was revoked | Paste the whole key again, or mint a new one |
| Could not reach Intelleta | No internet, or a short outage, during setup | Try again in a moment |
| No devices appear | Your account has no device yet | Add a device in the Intelleta app |
| A device's `source` says `cloud` | Home Assistant cannot reach it on your network. Usually the device and Home Assistant are on different networks (a guest network, a second router), or the device has not restarted since it joined this network | Put them on the same network. If they already are, restart the device: it reports its address each time it starts |
| Everything is unavailable | Home Assistant started or restarted while the internet was down, so it does not know your devices yet | Nothing. It recovers on its own when the internet returns |
| Your key is no longer accepted | The key was revoked | Mint a new key in the Intelleta app and paste it where Home Assistant asks. Your devices and their history stay |
