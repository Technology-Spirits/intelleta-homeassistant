"""Constants for the Intelleta integration.

⛔ THIS INTEGRATION TALKS TO OUR API AND TO THE CUBE'S OWN LOCAL ENDPOINT.
IT DOES NOT VENDOR THE DEVICE WIRE CONTRACT, and that is deliberate — three
reasons, all of which bite:

  1. This repository goes public at launch. Vendoring the device contract
     would publish the device protocol along with it.
  2. This integration is installed in customers' homes and updated on their
     schedule, not ours. Tying it to a contract it cannot be upgraded in step
     with would make every device contract change a release into people's
     houses.
  3. It does not need it. Readings come from the cube's local endpoint and
     everything else from our API — both of them our shapes to keep stable.

See card 87.
"""

DOMAIN = "intelleta"

# Config-entry keys.
#
# ⛔ THE PASSWORD IS NEVER ONE OF THESE. What is stored is a renewable
# credential; the password is used once, at sign-in, and then forgotten. The
# MTronic integration set this precedent and it is not up for revisiting.
CONF_CREDENTIAL = "credential"
CONF_ACCOUNT_ID = "account_id"

# How often the local endpoint is asked, when the cube is reachable on the
# home network. The cube publishes on its own schedule (30s..5min, settable);
# asking more often than it measures buys nothing but traffic.
DEFAULT_LOCAL_POLL_SECONDS = 30

# ⚠ EVERY CUSTOMER-VISIBLE STRING IN THIS INTEGRATION GOES THROUGH RAYE AND
# THOMAS. The technical identifier "intelleta" is settled — the company name.
# Names of products, screens and messages are not, and nothing user-facing
# should be invented here. Placeholders belong in strings.json where they are
# easy to find and replace, never scattered through the code.

# Where our API lives.
#
# ⛔⛔ THIS IS THE DEVELOPMENT ENDPOINT AND IT MUST NOT SHIP. Production has
# never been deployed — there is a production environment and nothing has ever
# been pushed to it — so there is no correct value to put here yet. Shipping
# this one would point every customer's Home Assistant at the environment we
# break things in, and it would work, right up until it did not.
#
# Card 96 owns the launch checklist. This line is on it.
API_BASE_URL = "https://adko43qx21.execute-api.eu-central-1.amazonaws.com"

# How often to ask the cloud, when the cloud is what we are asking.
#
# ⚠ SLOWER THAN THE LOCAL POLL, DELIBERATELY. The cube publishes on its own
# schedule — between 30 seconds and 5 minutes, chosen by the customer — so
# asking the cloud faster than the cube speaks costs requests and returns the
# same row again. The local path can afford to be eager because it is a request
# across the room.
DEFAULT_CLOUD_POLL_SECONDS = 60
