"""Config flow for the Tallinn Widgets integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_CONFIG_PATH,
    CONF_ELRON_NAME,
    CONF_ELRON_SCAN_INTERVAL,
    CONF_TRANSIT_NAME,
    CONF_TRANSIT_SCAN_INTERVAL,
    DEFAULT_CONFIG_PATH,
    DEFAULT_ELRON_NAME,
    DEFAULT_ELRON_SCAN_SECONDS,
    DEFAULT_TRANSIT_NAME,
    DEFAULT_TRANSIT_SCAN_SECONDS,
    DOMAIN,
)


def _entry_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_CONFIG_PATH,
                default=defaults.get(CONF_CONFIG_PATH, DEFAULT_CONFIG_PATH),
            ): str,
            vol.Required(
                CONF_TRANSIT_NAME,
                default=defaults.get(CONF_TRANSIT_NAME, DEFAULT_TRANSIT_NAME),
            ): str,
            vol.Required(
                CONF_ELRON_NAME,
                default=defaults.get(CONF_ELRON_NAME, DEFAULT_ELRON_NAME),
            ): str,
            vol.Required(
                CONF_TRANSIT_SCAN_INTERVAL,
                default=defaults.get(
                    CONF_TRANSIT_SCAN_INTERVAL, DEFAULT_TRANSIT_SCAN_SECONDS
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required(
                CONF_ELRON_SCAN_INTERVAL,
                default=defaults.get(CONF_ELRON_SCAN_INTERVAL, DEFAULT_ELRON_SCAN_SECONDS),
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
        }
    )


def _clean_input(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_CONFIG_PATH: str(user_input[CONF_CONFIG_PATH]).strip()
        or DEFAULT_CONFIG_PATH,
        CONF_TRANSIT_NAME: str(user_input[CONF_TRANSIT_NAME]).strip()
        or DEFAULT_TRANSIT_NAME,
        CONF_ELRON_NAME: str(user_input[CONF_ELRON_NAME]).strip()
        or DEFAULT_ELRON_NAME,
        CONF_TRANSIT_SCAN_INTERVAL: int(user_input[CONF_TRANSIT_SCAN_INTERVAL]),
        CONF_ELRON_SCAN_INTERVAL: int(user_input[CONF_ELRON_SCAN_INTERVAL]),
    }


class TallinnWidgetsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tallinn Widgets."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TallinnWidgetsOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial setup step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title="Tallinn Widgets",
                data=_clean_input(user_input),
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_entry_schema(),
        )


class TallinnWidgetsOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Tallinn Widgets."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=_clean_input(user_input),
            )

        defaults = dict(self._config_entry.data)
        defaults.update(self._config_entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=_entry_schema(defaults),
        )
