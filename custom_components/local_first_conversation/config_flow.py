"""Select an existing fallback without collecting model credentials."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import (
    CONF_FALLBACK,
    CONF_LISTENING_MARKER,
    DEFAULT_LISTENING_MARKER,
    DOMAIN,
)
from .conversation import valid_fallback


def fallback_schema(default: str | None = None) -> vol.Schema:
    """Offer conversation entities; validate the selection on submission."""
    return vol.Schema(
        {
            vol.Required(
                CONF_FALLBACK, default=default or vol.UNDEFINED
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="conversation")
            )
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one router per entry."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if valid_fallback(self.hass, user_input[CONF_FALLBACK]):
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
            errors[CONF_FALLBACK] = "invalid_fallback"
        schema = fallback_schema().extend(
            {vol.Required(CONF_NAME, default="Local First Conversation"): str}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """Change the fallback and listening indicator."""

    async def async_step_init(self, user_input=None):
        errors = {}
        marker = self.config_entry.options.get(
            CONF_LISTENING_MARKER, DEFAULT_LISTENING_MARKER
        )
        if user_input is not None:
            marker = user_input.get(CONF_LISTENING_MARKER, marker).strip()
            if not marker:
                errors[CONF_LISTENING_MARKER] = "empty_marker"
            if not valid_fallback(self.hass, user_input[CONF_FALLBACK]):
                errors[CONF_FALLBACK] = "invalid_fallback"
            if not errors:
                return self.async_create_entry(
                    data={**user_input, CONF_LISTENING_MARKER: marker}
                )
        current = self.config_entry.options.get(
            CONF_FALLBACK, self.config_entry.data[CONF_FALLBACK]
        )
        return self.async_show_form(
            step_id="init",
            data_schema=fallback_schema(current).extend(
                {
                    vol.Required(
                        CONF_LISTENING_MARKER, default=marker
                    ): selector.TextSelector()
                }
            ),
            errors=errors,
        )
