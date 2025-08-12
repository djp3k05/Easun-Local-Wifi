# custom_components/easun_inverter/__init__.py
"""The Easun ISolar Inverter integration."""
from __future__ import annotations
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DOMAIN = "easun_inverter"
PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Easun ISolar Inverter from a config entry."""
    _LOGGER.warning(
        "Setting up inverter with model: %s, config data: %s",
        entry.data.get("model"),
        entry.data,
    )
    # Forward the setup to the sensor platform.
    # The sensor platform will create the inverter object and coordinator.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Easun ISolar Inverter config entry: %s", entry.entry_id)

    # Unload the sensor platform first.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Retrieve the inverter instance stored in the domain data
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data and "inverter" in entry_data:
            inverter = entry_data["inverter"]
            # For ASCII models, we need to explicitly disconnect to release the port
            if hasattr(inverter, "client") and hasattr(inverter.client, "disconnect"):
                try:
                    _LOGGER.info("Disconnecting from ASCII inverter to release port.")
                    # Create a task to run the disconnect coroutine
                    await asyncio.create_task(inverter.client.disconnect())
                except Exception as e:
                    _LOGGER.error("Error during inverter disconnect: %s", e)
    
    return unload_ok
