# custom_components/easun_inverter/sensor.py
from datetime import timedelta
import logging

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
from easunpy import get_inverter

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    """Set up the Easun Inverter sensors from a config entry."""
    inverter = get_inverter(
        model=config_entry.data["model"],
        inverter_ip=config_entry.data["inverter_ip"],
        local_ip=config_entry.data["local_ip"]
    )

    async def async_update_data():
        """Fetch data from inverter."""
        try:
            return await inverter.get_all_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with inverter: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass, _LOGGER, name="easun_inverter",
        update_method=async_update_data,
        update_interval=timedelta(seconds=config_entry.options.get("scan_interval", 30)),
    )
    
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {"coordinator": coordinator, "inverter": inverter}
    
    # Map data types to their index in the tuple returned by get_all_data
    data_map = {"battery": 0, "pv": 1, "grid": 2, "output": 3, "system": 4, "rating": 5}

    def s(id, name, unit, type, attr, converter=None):
        """Helper to create sensor definitions."""
        return EasunSensor(coordinator, id, name, unit, type, attr, data_map.get(type), converter)

    sensors = [
        # Battery Sensors
        s("battery_voltage", "Battery Voltage", UnitOfElectricPotential.VOLT, "battery", "voltage"),
        s("battery_current", "Battery Current", UnitOfElectricCurrent.AMPERE, "battery", "current"),
        s("battery_power", "Battery Power", UnitOfPower.WATT, "battery", "power"),
        s("battery_soc", "Battery SOC", PERCENTAGE, "battery", "soc"),
        s("battery_temperature", "Inverter Temperature", UnitOfTemperature.CELSIUS, "battery", "temperature"),
        
        # PV Sensors
        s("pv_total_power", "PV Total Power", UnitOfPower.WATT, "pv", "total_power"),
        s("pv1_voltage", "PV1 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv1_voltage"),
        s("pv1_current", "PV1 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv1_current"),
        s("pv1_power", "PV1 Power", UnitOfPower.WATT, "pv", "pv1_power"),
        s("pv2_voltage", "PV2 Voltage", UnitOfElectricPotential.VOLT, "pv", "pv2_voltage"),
        s("pv2_current", "PV2 Current", UnitOfElectricCurrent.AMPERE, "pv", "pv2_current"),
        s("pv2_power", "PV2 Power", UnitOfPower.WATT, "pv", "pv2_power"),

        # Grid and Output Sensors
        s("grid_voltage", "Grid Voltage", UnitOfElectricPotential.VOLT, "grid", "voltage"),
        s("output_power", "Output Power", UnitOfPower.WATT, "output", "power"),
        s("output_load_percentage", "Output Load", PERCENTAGE, "output", "load_percentage"),
        
        # System Status Sensors
        s("operating_mode", "Operating Mode", None, "system", "mode_name"),
        s("warnings", "Device Warnings", None, "system", "warnings", lambda v: ", ".join(v) if v else "None"),

        # Rating Sensors (static data)
        s("rating_battery_type", "Rating Battery Type", None, "rating", "battery_type"),
        s("rating_max_charge_current", "Rating Max Charge Current", UnitOfElectricCurrent.AMPERE, "rating", "max_charging_current"),
        s("rating_output_priority", "Rating Output Priority", None, "rating", "output_source_priority"),
        s("rating_charger_priority", "Rating Charger Priority", None, "rating", "charger_source_priority"),
        s("rating_ac_output_voltage", "Rating AC Output Voltage", UnitOfElectricPotential.VOLT, "rating", "ac_output_rating_voltage"),
        s("rating_battery_float_v", "Rating Battery Float Voltage", UnitOfElectricPotential.VOLT, "rating", "battery_float_voltage"),
        s("rating_battery_bulk_v", "Rating Battery Bulk Voltage", UnitOfElectricPotential.VOLT, "rating", "battery_bulk_voltage"),
    ]
    
    add_entities(sensors)

class EasunSensor(SensorEntity):
    """Representation of an Easun Inverter sensor."""
    def __init__(self, coordinator, id_suffix, name, unit, data_type, data_attr, data_index, converter=None):
        self.coordinator = coordinator
        self._id_suffix = id_suffix
        self._name = name
        self._unit = unit
        self._data_type = data_type
        self._data_attr = data_attr
        self._data_index = data_index
        self._value_converter = converter
        self._attr_native_value = None

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
        return {"identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)}}

    @property
    def available(self) -> bool:
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
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))
        self._handle_coordinator_update()
