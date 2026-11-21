# Installing Intelleta in Home Assistant

You need Home Assistant with HACS, an Intelleta account with at least one device, and an internet connection during setup. HACS (the Home Assistant Community Store) is how Home Assistant installs integrations made outside its own team. No HACS yet? Install it first by following [HACS's own guide](https://hacs.xyz/docs/use/download/download/), then come back here. After setup, Home Assistant reads each device over your own network, so readings keep coming if the internet goes down, with one exception, under [If your internet goes down](#if-your-internet-goes-down).

## 1. Install Intelleta from HACS

In HACS, open **Integrations**, then **Custom repositories** from the three-dot menu. Paste `https://github.com/Technology-Spirits/intelleta-homeassistant`, choose **Integration**, and press **Add**. Download **Intelleta**, then restart Home Assistant.

## 2. Make a key

In the Intelleta app, go to **Settings → Home Assistant → Make a key**. There is nothing to type.

Copy the key now, or press **Share** to send it to the computer you use for Home Assistant. It is shown once and never again. If you lose it, press **Make a new key** on the same page. The old key stops working.

## 3. Connect

In Home Assistant, go to **Settings → Devices & services → Add integration**, choose **Intelleta**, and paste the key. The Home Assistant page in the app changes to **Connected** on its own.

## 4. Choose what Andy can control

In Home Assistant, go to **Settings → Devices & services → Intelleta** and press **Configure**. Under **Shared with Intelleta**, use **Choose entity** to add each light, switch, scene or other thing you want to share, then press **Submit**. Only what you add here leaves your home, and only its name, kind and room.

Then, in the Intelleta app, open a device, go to **Voice control**, and pick up to six of them. Say "Hi Andy, turn on" and the name. Want more than six? Make a scene in Home Assistant that does several things at once, and pick the scene.

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
| The key was not accepted | Part of it was missed when copying, or a newer key replaced it | Paste the whole key again, or make a new one in the Intelleta app |
| Could not reach Intelleta | No internet, or a short outage, during setup | Try again in a moment |
| No devices appear | Your account has no device yet | Add a device in the Intelleta app |
| A device's `source` says `cloud` | Home Assistant cannot reach it on your network. Usually the device and Home Assistant are on different networks (a guest network, a second router), or the device has not restarted since it joined this network | Put them on the same network. If they already are, restart the device: it reports its address each time it starts |
| Everything is unavailable | Home Assistant started or restarted while the internet was down, so it does not know your devices yet | Nothing. It recovers on its own when the internet returns |
| Your key is no longer accepted | The key was replaced, or Home Assistant was disconnected in the app | Make a new key in the Intelleta app (**Settings → Home Assistant → Make a new key**) and paste it where Home Assistant asks. Your devices and their history stay |
| Andy says Home Assistant didn't answer | Home Assistant is off, offline, or slow to answer | Check that Home Assistant is on and online. The app's Home Assistant page shows when it was last heard from |
| A thing is missing from the app's list | It is not shared in Home Assistant | Add it under **Intelleta → Configure** |
