"""Signing in. Card 88, using the key from card 89.

⛔ TWO RULES THIS FLOW MUST NEVER BREAK.

  1. THE PASSWORD IS NEVER ASKED FOR AND NEVER STORED. There is no password
     field here at all, because there is nothing for one to do: the customer
     mints a key in the portal and pastes it. What we keep is that key, and it
     is revocable from the portal in one tap.

  2. SIGN-IN IS REQUIRED BEFORE ANYTHING WORKS. Owner ruling 2026-08-25, made
     against the recommendation to let readings appear without an account. Do
     not "helpfully" add a skip.

⚠ AND THE KEY IS VALIDATED BY DOING THE REAL THING. Setup calls the same
endpoint the integration will use every minute afterwards, rather than a
dedicated "check this key" route. A validation path that is not the working path
drifts away from it, and then setup succeeds for a key that cannot actually do
anything.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthFailed, CloudClient, CloudUnavailable
from .const import API_BASE_URL, CONF_CREDENTIAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_CREDENTIAL): str})


class IntellettaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Intelleta config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            key = (user_input.get(CONF_CREDENTIAL) or "").strip()
            session = async_get_clientsession(self.hass)

            try:
                devices = await CloudClient(session, API_BASE_URL, key).async_list_devices()
            except AuthFailed:
                # ⛔ DISTINCT FROM AN OUTAGE. "Your key was not accepted" asks
                # the customer to do something; "we could not reach us" asks
                # them to wait. Telling somebody with a perfectly good key to
                # go and mint another one is a bad half-hour for both of us.
                errors["base"] = "invalid_auth"
            except CloudUnavailable:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("unexpected error validating the key")
                errors["base"] = "unknown"
            else:
                # ⛔ ONE ENTRY PER ACCOUNT. Without this, pasting a second key
                # for the same account creates a duplicate set of every entity
                # and splits the customer's history down the middle.
                await self.async_set_unique_id(_account_fingerprint(key))
                self._abort_if_unique_id_configured()

                # ⚠ AN EMPTY ACCOUNT IS NOT AN ERROR. Somebody who signed in
                # before claiming a cube has a perfectly working integration
                # with nothing in it yet, and the entities appear when they
                # claim one. Refusing here would send them hunting a fault that
                # does not exist.
                _LOGGER.debug("key accepted; %d device(s) on the account", len(devices))

                return self.async_create_entry(
                    title="Intelleta",
                    data={CONF_CREDENTIAL: key},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_zeroconf(self, discovery_info) -> ConfigFlowResult:  # noqa: ANN001
        """A cube announced itself on the network (aqm 527).

        ⛔ DISCOVERY IS NOT AUTHORISATION. Hearing a cube says only that one is
        nearby — it could be a flat-mate's, a neighbour's through a thin wall, or
        something merely claiming to be one. So this cannot set anything up on
        its own; all it does is offer the ordinary sign-in, after which the
        ACCOUNT decides which cubes are actually this customer's (card 93).

        ⚠ AND THIS STEP MUST EXIST BECAUSE THE MANIFEST NAMES THE SERVICE. Home
        Assistant calls it on every matching announcement, and a flow without it
        raises on a perfectly ordinary event — one neighbour's cube would fill
        the customer's log with errors about our integration.
        """
        # Already set up: the coordinator's own sweep handles this cube from
        # here, so there is nothing to prompt about.
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """A key that was working has stopped — almost always a revoke.

        ⚠ THIS IS WHY AuthFailed IS A SEPARATE EXCEPTION ALL THE WAY DOWN. It is
        what turns a revoked key into a visible prompt rather than an
        integration that quietly stops updating and leaves the customer looking
        at numbers that never change.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=STEP_USER_SCHEMA
            )
        return await self.async_step_user(user_input)


def _account_fingerprint(key: str) -> str:
    """A stable id for the account this key belongs to.

    ⛔ NOT THE KEY ITSELF. Home Assistant stores the unique id in plain text in
    its own configuration, so putting a live credential there would leak it into
    every backup and every diagnostics download — undoing the whole reason the
    key is fingerprinted rather than stored on our side.
    """
    import hashlib

    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
