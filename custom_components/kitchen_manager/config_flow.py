"""Config flow for Kitchen Manager."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries

from .const import DOMAIN


class KitchenManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kitchen Manager."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Set up the single household Kitchen Manager instance."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Kitchen Manager", data={})

        return self.async_show_form(step_id="user")
