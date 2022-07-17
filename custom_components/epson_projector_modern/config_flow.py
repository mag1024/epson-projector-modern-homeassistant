"""Config flow for epson integration."""
from __future__ import annotations

import logging
import asyncio
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_UNIQUE_ID
from homeassistant.data_entry_flow import FlowResult

from .projector import Projector
from .const import DOMAIN

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_NAME, default="projector"): str,
    }
)

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bosch Alarm."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            p = Projector(user_input[CONF_HOST])
            try:
                await p.connect()
                serial = p.serial_number
                await p.disconnect()
            except RuntimeError:
                errors["base"] = "cannot_connect"
            else:
                unique_id = f'epson_{serial}'
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                user_input[CONF_UNIQUE_ID] = unique_id
                return self.async_create_entry(
                    title=user_input.pop(CONF_NAME), data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )
