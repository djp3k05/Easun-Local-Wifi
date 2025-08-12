# custom_components/easun_inverter/sensor.py
"""Support for Easun Inverter sensors."""
from datetime import timedelta
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    UnitOfPower, UnitOfElectricCurrent, UnitOfElectricPotential,
    UnitOfTemperature, UnitOfFrequency, UnitOfApparentPower,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import DOMAIN
from easunpy import get_inverter

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    """Set up the Easun Inverter sensors from a config entry."""
    _LOGGER.debug("Setting up Easun Inverter sensors for entry: %s", config_entry.entry_id)

    try:
        inverter = get_inverter(
            model=config_entry.data["model"],
            inverter_ip=config_entry.data["inverter_ip"],
            local_ip=config_entry.data["local_ip"]
        )
    except ValueError as e:
        _LOGGER.error("Failed to get inverter model: %s", e)
        return

    async def async_update_data():
        """Fetch data from inverter."""
        try:
            # This now returns a tuple with 6 elements for the ASCII model
            return await inverter.get_all_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with inverter: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass, _LOGGER, name=f"easun_inverter_{config_entry.entry_id}",
        update_method=async_update_data,
        update_interval=timedelta(seconds=config_entry.options.get("scan_interval", 30)),
    )
    
    await coordinator.async_config_entry_first_refresh()
    
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "coordinator": coordinator, 
        "inverter": inverter
    }
    
    # Map data types to their index in the tuple returned by get_all_data
    # (battery, pv, grid, output, system, rating)
    data_map = {"battery": 0, "pv": 1, "grid": 2, "output": 3, "system": 4, "rating": 5}

    def create_sensor(id_suffix, name, unit, data_type, data_attr, converter=None):
        """Helper function to create sensor definitions."""
        return EasunSensor(
            coordinator, id_suffix, name, unit, 
            data_type, data_attr, data_map.get(data_type), converter
        )

    sensors_to_add = [
        # Battery Sensors
        create_sensor("battery_voltage", "Battery Voltage", UnitOfElectricPotential.VOLT, "battery", "voltage"),
        create_sensor("battery_current", "Battery Current", UnitOfElectricCurrent.AMPERE, "battery", "current"),
        create_sensor("battery_power", "Battery Power", UnitOfPower.WATT, "battery", "power"),
        create_sensor("battery_soc", "Battery SOC", PERCENTAGE, "battery", "soc"),
        create_sensor("battery_temperature", "Inverter Temperature", UnitOfTemperature.CELSIUS, "battery", "temperature"),
        
        # PV Sensors
        create_sensor("pv_total_power", "PV Total Power", UnitOfPower.WATT, "pv", "total_power"),
        create_sensor("pv1_voltage", "PV1 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv1_voltage"),
        create_sensor("pv1_current", "PV1 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv1_current"),
        create_sensor("pv1_power", "PV1 Power", UnitOfPower.WATT, "pv", "pv1_power"),
        create_sensor("pv2_voltage", "PV2 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv2_voltage"),
        create_sensor("pv2_current", "PV2 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv2_current"),
        create_sensor("pv2_power", "PV2 Power", UnitOfPower.WATT, "pv", "pv2_power"),

        # Grid and Output Sensors
        create_sensor("grid_voltage", "Grid Voltage", UnitOfElectricPotential.VOLT, "grid", "voltage"),
        create_sensor("output_power", "Output Power", UnitOfPower.WATT, "output", "power"),
        create_sensor("output_load_percentage", "Output Load", PERCENTAGE, "output", "load_percentage"),
        
        # System Status Sensors
        create_sensor("operating_mode", "Operating Mode", None, "system", "mode_name"),
        create_sensor("warnings", "Device Warnings", None, "system", "warnings", lambda v: ", ".join(v) if v else "None"),

        # Rating Sensors (static data from QPIRI)
        create_sensor("rating_battery_type", "Rating Battery Type", None, "rating", "battery_type"),
        create_sensor("rating_max_charge_current", "Rating Max Charge Current", UnitOfElectricCurrent.AMPERE, "rating", "max_charging_current"),
        create_sensor("rating_output_priority", "Rating Output Priority", None, "rating", "output_source_priority"),
        create_sensor("rating_charger_priority", "Rating Charger Priority", None, "rating", "charger_source_priority"),
        create_sensor("rating_ac_output_voltage", "Rating AC Output Voltage", UnitOfElectricPotential.VOLT, "rating", "ac_output_rating_voltage"),
        create_sensor("rating_battery_float_v", "Rating Battery Float Voltage", UnitOfElectricPotential.VOLT, "rating", "battery_float_voltage"),
        create_sensor("rating_battery_bulk_v", "Rating Battery Bulk Voltage", UnitOfElectricPotential.VOLT, "rating", "battery_bulk_voltage"),
    ]
    
    add_entities(sensors_to_add)

class EasunSensor(SensorEntity):
    """Representation of an Easun Inverter sensor."""
    _attr_has_entity_name = True

    def __init__(self, coordinator, id_suffix, name, unit, data_type, data_attr, data_index, converter=None):
        self.coordinator = coordinator
        self._id_suffix = id_suffix
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._data_type = data_type
        self._data_attr = data_attr
        self._data_index = data_index
        self._value_converter = converter
        self._attr_unique_id = f"easun_inverter_{self.coordinator.config_entry.entry_id}_{self._id_suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "name": f"Easun Inverter ({self.coordinator.config_entry.data.get('model')})",
            "manufacturer": "Easun Power / Voltronic",
            "model": self.coordinator.config_entry.data.get('model'),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None and
            self._data_index is not None and
            len(self.coordinator.data) > self._data_index and
            self.coordinator.data[self._data_index] is not None
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.available:
            data_obj = self.coordinator.data[self._data_index]
            value = getattr(data_obj, self._data_attr, None)
            if self._value_converter:
                self._attr_native_value = self._value_converter(value)
            else:
                self._attr_native_value = value
        else:
            self._attr_native_value = None
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()
