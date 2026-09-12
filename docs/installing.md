# Installing Intelleta in Home Assistant

You need Home Assistant with HACS, an Intelleta account with at least one device, and an internet connection during setup.

## 1. Add the integration

In HACS, open **Integrations**, then **Custom repositories** from the three-dot menu. Paste `https://github.com/Technology-Spirits/intelleta-homeassistant`, choose **Integration**, and press **Add**. Download **Intelleta**, then restart Home Assistant.

## 2. Mint a key

In the Intelleta portal, go to **Account → Integration keys → Mint a key**. When it asks what will use the key, type a name such as Home Assistant.

Copy the key immediately: it is shown once and never again. If you lose it, mint another and revoke the old one in the same place.

## 3. Connect

In Home Assistant, go to **Settings → Devices & services → Add integration**, choose **Intelleta**, and paste the key.

## What you get

Each device on your account appears in Home Assistant with exactly the readings it measures. Readings arrive through your Intelleta account.

## Troubleshooting

| What you see | Why | What to do |
|---|---|---|
| The key was not accepted | Part of it was missed when copying, or it was revoked | Paste the whole key again, or mint a new one |
| Could not reach Intelleta | No internet, or a short outage | Try again in a moment |
| No devices appear | Your account has no device yet | Add a device in the Intelleta app |
