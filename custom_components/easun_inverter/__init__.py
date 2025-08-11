# custom_components/easun_inverter/__init__.py
"""The Easun ISolar Inverter integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
import logging
from easunpy.modbusclient import create_request 
from datetime import datetime
import json
import os
from aiofiles import open as async_open
from aiofiles.os import makedirs
import asyncio

_LOGGER = logging.getLogger(__name__)

DOMAIN = "easun_inverter"

# List of platforms to support. There should be a matching .py file for each,
# eg. switch.py and sensor.py
PLATFORMS: list[Platform] = [Platform.SENSOR]

DOMAIN = "easun_inverter"

# Use config_entry_only_config_schema since we only support config flow
CONFIG_SCHEMA = cv.config_entry_only_config_schema("easun_inverter")

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version < 4:
        new_data = {**config_entry.data}
        
        # Add model with default value if it doesn't exist
        if "model" not in new_data:
            new_data["model"] = "ISOLAR_SMG_II_11K"
            
        # Update the entry with new data and version
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=4
        )
        _LOGGER.info("Migration to version %s successful", 4)

    return True

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Easun ISolar Inverter component."""
    _LOGGER.debug("Set up the Easun ISolar Inverter component")
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Easun ISolar Inverter from a config entry."""
    if entry.version < 4:
        if not await async_migrate_entry(hass, entry):
            return False

    model = entry.data["model"]  # No default - should be required
    _LOGGER.warning(f"Setting up inverter with model: {model}, config data: {entry.data}")
    
    # Domain data
    hass.data.setdefault(DOMAIN, {})
    
    async def handle_register_scan(call: ServiceCall) -> None:
        """Handle the register scan service."""
        start = call.data.get("start_register", 0)
        count = call.data.get("register_count", 5)
        
        # Get the coordinator from the entry we stored in sensor.py
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if not entry_data or "coordinator" not in entry_data:
            _LOGGER.error("No coordinator found. Is the integration set up?")
            return
            
        coordinator = entry_data["coordinator"]
        inverter = coordinator._isolar
        
        # Check protocol
        if coordinator.model_config.protocol == "ascii":
            _LOGGER.warning("Register scan not supported for ASCII protocol models like Axpert MKS2")
            hass.data[DOMAIN]["register_scan"] = {
                "timestamp": datetime.now().isoformat(),
                "error": "Not supported for ASCII protocol"
            }
            return

        _LOGGER.debug(f"Starting register scan from {start} for {count} registers")
        
        # Create register groups in chunks of 10
        register_groups = []
        for chunk_start in range(start, start + count, 10):
            chunk_size = min(10, start + count - chunk_start)  # Handle small gaps
            register_groups.append((chunk_start, chunk_size))
        
        results = []
        for group_start, group_count in register_groups:
            request = create_request(0x0777, 0x0001, 0x01, 0x03, group_start, group_count)
            response_hex = run_single_request(entry.data["inverter_ip"], entry.data["local_ip"], request)
            
            if response_hex:
                decoded = decode_modbus_response(response_hex, group_count)
                for i in range(group_count):
                    reg_address = group_start + i
                    value = decoded[i] if i < len(decoded) else None
                    results.append({
                        "register": reg_address,
                        "hex": f"0x{reg_address:04x}",
                        "value": value,
                        "response": response_hex if i == 0 else None  # Only store response once per group
                    })
            else:
                for i in range(group_count):
                    results.append({
                        "register": group_start + i,
                        "hex": f"0x{group_start + i:04x}",
                        "value": None,
                        "response": "No response"
                    })
            
            await asyncio.sleep(0.5)  # Delay between groups
        
        # Store results
        scan_data = {
            "timestamp": datetime.now().isoformat(),
            "results": results,
            "start": start,
            "count": count
        }
        hass.data[DOMAIN]["register_scan"] = scan_data
        
        # Log summary
        valid_responses = [r for r in results if r["value"] is not None]
        _LOGGER.info(f"Register scan complete. Found {len(valid_responses)} valid values")

    async def handle_device_scan(call: ServiceCall) -> None:
        """Handle the device ID scan service."""
        start_id = call.data.get("start_id", 0)
        end_id = call.data.get("end_id", 255)
        
        entry_data = hass.data[DOMAIN].get(entry.entry_id)
        if not entry_data:
            _LOGGER.error("No entry data found")
            return
            
        coordinator = entry_data.get("coordinator")
        if not coordinator:
            _LOGGER.error("No coordinator found")
            return
            
        if coordinator.model_config.protocol == "ascii":
            _LOGGER.warning("Device scan not supported for ASCII protocol models")
            hass.data[DOMAIN]["device_scan"] = {
                "timestamp": datetime.now().isoformat(),
                "error": "Not supported for ASCII protocol"
            }
            return

        _LOGGER.debug(f"Starting device ID scan from {start_id} to {end_id}")
        
        results = []
        for device_id in range(start_id, end_id + 1):
            request = create_request(0x0777, 0x0001, device_id, 0x03, 0, 1)
            response_hex = run_single_request(entry.data["inverter_ip"], entry.data["local_ip"], request)
            
            result = {
                "device_id": device_id,
                "hex": f"0x{device_id:02x}",
                "request": request,
                "response": response_hex,
            }
        
            ERROR_RESPONSE = "00010002ff04"  # Protocol error response
            
            if response_hex: 
                if response_hex[4:] == ERROR_RESPONSE:
                    result["status"] = "Protocol Error"
                    _LOGGER.debug(f"Device 0x{device_id:02x} gave protocol error: {response_hex}")
                else:
                    result["status"] = "Valid Response"
                    result["decoded"] = decode_modbus_response(response_hex, 1)
                    _LOGGER.debug(f"Device 0x{device_id:02x} gave valid response: {response_hex}")
            else:
                _LOGGER.debug(f"Device 0x{device_id:02x} gave no response")
                result["status"] = "No Response"
            
            results.append(result)
            
            await asyncio.sleep(0.1)  # Small delay between requests
        
        # Store results
        scan_data = {
            "timestamp": datetime.now().isoformat(),
            "results": results,
            "start_id": start_id,
            "end_id": end_id
        }
        hass.data[DOMAIN]["device_scan"] = scan_data
        
        # Log summary
        valid_responses = [r for r in results if r["status"] == "Valid Response"]
        _LOGGER.info(f"Device scan complete. Found {len(valid_responses)} valid responses")
        for r in valid_responses:
            _LOGGER.info(f"Device {r['hex']}: Request={r['request']}, Response={r['response']}, Decoded={r['decoded']}")

    # Register both services
    hass.services.async_register(DOMAIN, "register_scan", handle_register_scan)
    hass.services.async_register(DOMAIN, "device_scan", handle_device_scan)
    
    # Forward the setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Easun ISolar Inverter config entry")
    
    # Cleanup any update listeners
    if entry.entry_id in hass.data[DOMAIN]:
        if "update_listener" in hass.data[DOMAIN][entry.entry_id]:
            _LOGGER.debug("Cancelling update listener")
            hass.data[DOMAIN][entry.entry_id]["update_listener"]()
    
    # Unload the sensor platform
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # Clean up domain data
    if unload_ok and entry.entry_id in hass.data[DOMAIN]:
        _LOGGER.debug("Removing entry data")
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
