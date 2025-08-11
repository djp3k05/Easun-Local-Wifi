# custom_components/easun_inverter/config_flow.py
"""Config flow for Easun Inverter integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging

from . import DOMAIN
from easunpy.discover import discover_device
from easunpy.utils import get_local_ip
from easunpy.models import MODEL_CONFIGS

DEFAULT_SCAN_INTERVAL = 30
_LOGGER = logging.getLogger(__name__)

class EasunInverterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Easun Inverter."""

    VERSION = 4 # Keep version, migration logic is fine

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            inverter_ip = user_input.get("inverter_ip")
            local_ip = user_input.get("local_ip")
            scan_interval = user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL)
            model = user_input.get("model")
            
            if not inverter_ip or not local_ip:
                errors["base"] = "missing_ip"
            else:
                entry_data = {
                    "inverter_ip": inverter_ip,
                    "local_ip": local_ip,
                    "scan_interval": scan_interval,
                    "model": model,
                }
                return self.async_create_entry(
                    title=f"Easun Inverter ({inverter_ip}) - {model}",
                    data=entry_data,
                )

        inverter_ip = await self.hass.async_add_executor_job(discover_device)
        local_ip = await self.hass.async_add_executor_job(get_local_ip)

        # Get available models, with the new ASCII model first
        available_models = ["VOLTRONIC_ASCII"] + [m for m in MODEL_CONFIGS.keys() if m != "VOLTRONIC_ASCII"]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("inverter_ip", default=inverter_ip or ""): str,
                vol.Required("local_ip", default=local_ip or ""): str,
                vol.Required("model", default="VOLTRONIC_ASCII"): vol.In(available_models),
                vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=5, max=3600)
                ),
            }),
            errors=errors,
            description_placeholders={
                "model_list": ", ".join(available_models)
            }
        )

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            # We need to reload the integration if the model or IPs change
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=user_input, options={"scan_interval": user_input["scan_interval"]}
            )
            return self.async_create_entry(title="", data={})


        current_data = self.config_entry.data
        available_models = ["VOLTRONIC_ASCII"] + [m for m in MODEL_CONFIGS.keys() if m != "VOLTRONIC_ASCII"]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("inverter_ip", default=current_data.get("inverter_ip")): str,
                vol.Required("local_ip", default=current_data.get("local_ip")): str,
                vol.Required("model", default=current_data.get("model")): vol.In(available_models),
                vol.Optional(
                    "scan_interval",
                    default=self.config_entry.options.get("scan_interval", current_data.get("scan_interval", DEFAULT_SCAN_INTERVAL))
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            })
        )
