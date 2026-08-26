"""Config flow for Intelleta.

Scaffold only (card 87) — it presents the shape and stores nothing real. The
sign-in itself is card 88, and the credential it exchanges for is card 89.

⛔ TWO RULES THIS FLOW MUST NEVER BREAK, written here because a scaffold is
where they get forgotten:

  1. THE PASSWORD IS NOT STORED. It is used once and forgotten; what persists
     is a renewable credential. If you find yourself putting CONF_PASSWORD in
     the entry data, stop.
  2. SIGN-IN IS REQUIRED BEFORE ANYTHING WORKS. Owner ruling 2026-08-25, made
     against the recommendation to let readings appear without an account. Do
     not "helpfully" add a skip.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class IntellettaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Intelleta config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
            )

        # Card 88 replaces this: sign in, exchange for a credential, discover
        # the account's devices. Until then the scaffold refuses rather than
        # creating an entry that promises something it cannot do.
        return self.async_abort(reason="not_implemented")
