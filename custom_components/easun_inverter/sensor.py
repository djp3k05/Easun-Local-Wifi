# custom_components/easun_inverter/sensor.py
"""Support for Easun Inverter sensors."""
from datetime import datetime, timedelta
import logging
import asyncio

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    UnitOfPower, UnitOfElectricCurrent, UnitOfElectricPotential,
    UnitOfTemperature, UnitOfFrequency, UnitOfApparentPower,
    UnitOfEnergy, PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import DOMAIN
from easunpy import get_inverter # Use the new factory function

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Easun Inverter sensors from a config entry."""
    _LOGGER.debug("Setting up Easun Inverter sensors")
    
    inverter_ip = config_entry.data["inverter_ip"]
    local_ip = config_entry.data["local_ip"]
    model = config_entry.data["model"]
    scan_interval = config_entry.options.get("scan_interval", config_entry.data.get("scan_interval", 30))

    try:
        inverter = get_inverter(model=model, inverter_ip=inverter_ip, local_ip=local_ip)
    except ValueError as e:
        _LOGGER.error(f"Failed to initialize inverter: {e}")
        return

    async def async_update_data():
        """Fetch data from inverter."""
        try:
            # The get_all_data method is now standardized across inverter types
            return await inverter.get_all_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with inverter: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="easun_inverter",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )
    
    # Fetch initial data so we have it before adding entities
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator for services
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = {"coordinator": coordinator, "inverter": inverter}
    
    # Define sensors
    sensors = [
        EasunSensor(coordinator, "battery_voltage", "Battery Voltage", UnitOfElectricPotential.VOLT, "battery", "voltage"),
        EasunSensor(coordinator, "battery_current", "Battery Current", UnitOfElectricCurrent.AMPERE, "battery", "current"),
        EasunSensor(coordinator, "battery_power", "Battery Power", UnitOfPower.WATT, "battery", "power"),
        EasunSensor(coordinator, "battery_soc", "Battery State of Charge", PERCENTAGE, "battery", "soc"),
        EasunSensor(coordinator, "battery_temperature", "Battery Temperature", UnitOfTemperature.CELSIUS, "battery", "temperature"),
        
        EasunSensor(coordinator, "pv_total_power", "PV Total Power", UnitOfPower.WATT, "pv", "total_power"),
        EasunSensor(coordinator, "pv_charging_power", "PV Charging Power", UnitOfPower.WATT, "pv", "charging_power"),
        EasunSensor(coordinator, "pv_charging_current", "PV Charging Current", UnitOfElectricCurrent.AMPERE, "pv", "charging_current"),
        EasunSensor(coordinator, "pv1_voltage", "PV1 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv1_voltage"),
        EasunSensor(coordinator, "pv1_current", "PV1 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv1_current"),
        EasunSensor(coordinator, "pv1_power", "PV1 Power", UnitOfPower.WATT, "pv", "pv1_power"),
        EasunSensor(coordinator, "pv2_voltage", "PV2 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv2_voltage"),
        EasunSensor(coordinator, "pv2_current", "PV2 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv2_current"),
        EasunSensor(coordinator, "pv2_power", "PV2 Power", UnitOfPower.WATT, "pv", "pv2_power"),
        EasunSensor(coordinator, "pv_generated_today", "PV Generated Today", UnitOfEnergy.KILO_WATT_HOUR, "pv", "pv_generated_today"),
        EasunSensor(coordinator, "pv_generated_total", "PV Generated Total", UnitOfEnergy.KILO_WATT_HOUR, "pv", "pv_generated_total"),

        EasunSensor(coordinator, "grid_voltage", "Grid Voltage", UnitOfElectricPotential.VOLT, "grid", "voltage"),
        EasunSensor(coordinator, "grid_power", "Grid Power", UnitOfPower.WATT, "grid", "power"),
        EasunSensor(coordinator, "grid_frequency", "Grid Frequency", UnitOfFrequency.HERTZ, "grid", "frequency", lambda v: v / 100 if v else None),

        EasunSensor(coordinator, "output_voltage", "Output Voltage", UnitOfElectricPotential.VOLT, "output", "voltage"),
        EasunSensor(coordinator, "output_current", "Output Current", UnitOfElectricCurrent.AMPERE, "output", "current"),
        EasunSensor(coordinator, "output_power", "Output Power", UnitOfPower.WATT, "output", "power"),
        EasunSensor(coordinator, "output_apparent_power", "Output Apparent Power", UnitOfApparentPower.VOLT_AMPERE, "output", "apparent_power"),
        EasunSensor(coordinator, "output_load_percentage", "Output Load Percentage", PERCENTAGE, "output", "load_percentage"),
        EasunSensor(coordinator, "output_frequency", "Output Frequency", UnitOfFrequency.HERTZ, "output", "frequency", lambda v: v / 100 if v else None),

        EasunSensor(coordinator, "operating_mode", "Operating Mode", None, "system", "mode_name"),
        EasunSensor(coordinator, "inverter_time", "Inverter Time", None, "system", "inverter_time"),
    ]
    
    add_entities(sensors)


class EasunSensor(SensorEntity):
    """Representation of an Easun Inverter sensor."""

    def __init__(self, coordinator, id_suffix, name, unit, data_type, data_attr, value_converter=None):
        self.coordinator = coordinator
        self._id_suffix = id_suffix
        self._name = name
        self._unit = unit
        self._data_type = data_type
        self._data_attr = data_attr
        self._value_converter = value_converter

    @property
    def unique_id(self):
        return f"easun_inverter_{self.coordinator.config_entry.entry_id}_{self._id_suffix}"

    @property
    def name(self):
        return f"Easun {self._name}"

    @property
    def native_unit_of_measurement(self):
        return self._unit

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": f"Easun Inverter ({self.coordinator.config_entry.data.get('model')})",
            "manufacturer": "Easun Power",
            "model": self.coordinator.config_entry.data.get('model'),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data:
            data_map = {"battery": 0, "pv": 1, "grid": 2, "output": 3, "system": 4}
            data_index = data_map.get(self._data_type)
            
            if data_index is not None and self.coordinator.data[data_index]:
                value = getattr(self.coordinator.data[data_index], self._data_attr, None)
                if self._value_converter:
                    self._attr_native_value = self._value_converter(value)
                else:
                    self._attr_native_value = value
            else:
                self._attr_native_value = None
        else:
            self._attr_native_value = None
            
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        # Call it once to set the initial state
        self._handle_coordinator_update()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._attr_native_value
