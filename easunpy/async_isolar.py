# easunpy/async_isolar.py
# This file now acts as the main class for Modbus-based inverters.
# The logic has been separated from the new ASCII inverter logic.

import logging
from typing import List, Optional, Dict, Tuple, Any
from .async_modbusclient import AsyncModbusClient
from .modbusclient import create_request, decode_modbus_response
from .models import BatteryData, PVData, GridData, OutputData, SystemStatus, OperatingMode, MODEL_CONFIGS, ModelConfig
import datetime

logger = logging.getLogger(__name__)

class AsyncISolar:
    def __init__(self, inverter_ip: str, local_ip: str, model: str = "ISOLAR_SMG_II_11K"):
        self.client = AsyncModbusClient(inverter_ip=inverter_ip, local_ip=local_ip)
        self._transaction_id = 0x0772
        
        if model not in MODEL_CONFIGS:
            raise ValueError(f"Unknown inverter model: {model}. Available models: {list(MODEL_CONFIGS.keys())}")
        
        self.model = model
        self.model_config = MODEL_CONFIGS[model]
        if self.model_config.protocol != 'modbus':
            raise ValueError(f"Model {model} uses protocol '{self.model_config.protocol}', not 'modbus'.")
            
        logger.info(f"AsyncISolar (Modbus) initialized with model: {model}")

    def update_model(self, model: str):
        """Update the model configuration."""
        if model not in MODEL_CONFIGS:
            raise ValueError(f"Unknown inverter model: {model}. Available models: {list(MODEL_CONFIGS.keys())}")
        
        logger.info(f"Updating AsyncISolar to model: {model}")
        self.model = model
        self.model_config = MODEL_CONFIGS[model]

    def _get_next_transaction_id(self) -> int:
        """Get next transaction ID and increment counter."""
        current_id = self._transaction_id
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return current_id

    async def _read_registers_bulk(self, register_groups: list[tuple[int, int]], data_format: str = "Int") -> list[Optional[list[int]]]:
        """Read multiple groups of registers in a single connection."""
        try:
            requests = [
                create_request(self._get_next_transaction_id(), 0x0001, 0x00, 0x03, start, count).encode()
                for start, count in register_groups
            ]
            
            logger.debug(f"Sending bulk request for register groups: {register_groups}")
            responses = await self.client.send_bulk(requests)
             
            decoded_groups = [None] * len(register_groups)
            
            for i, (response, (_, count)) in enumerate(zip(responses, register_groups)):
                try:
                    if response:
                        decoded = decode_modbus_response(response, count, data_format)
                        logger.debug(f"Decoded values for group {i}: {decoded}")
                        decoded_groups[i] = decoded
                    else:
                        logger.warning(f"No response for register group {register_groups[i]}")
                except Exception as e:
                    logger.warning(f"Failed to decode register group {register_groups[i]}: {e}")
                
            return decoded_groups
            
        except Exception as e:
            logger.error(f"Error reading register groups: {str(e)}")
            return [None] * len(register_groups)

    async def get_all_data(self) -> tuple[Optional[BatteryData], Optional[PVData], Optional[GridData], Optional[OutputData], Optional[SystemStatus]]:
        """Get all inverter data in a single bulk request."""
        logger.info(f"Getting all data for Modbus model: {self.model}")
        
        register_groups = self._create_register_groups()
        
        results = await self._read_registers_bulk(register_groups)
        if not results:
            return None, None, None, None, None
            
        values = {}
        
        for i, (start_address, count) in enumerate(register_groups):
            if results[i] is None:
                continue
                
            for reg_name, config in self.model_config.register_map.items():
                if config.address >= start_address and config.address < start_address + count:
                    idx = config.address - start_address
                    if idx < len(results[i]):
                        values[reg_name] = self.model_config.process_value(reg_name, results[i][idx])
        
        battery = self._create_battery_data(values)
        pv = self._create_pv_data(values)
        grid = self._create_grid_data(values)
        output = self._create_output_data(values)
        status = self._create_system_status(values)
        
        return battery, pv, grid, output, status
        
    def _create_register_groups(self) -> list[tuple[int, int]]:
        """Create optimized register groups for reading."""
        addresses = sorted([
            config.address for config in self.model_config.register_map.values() if config.address > 0
        ])
        
        if not addresses:
            return []
            
        groups = []
        current_start = addresses[0]
        current_end = current_start
        
        for addr in addresses[1:]:
            if addr <= current_end + 10:
                current_end = addr
            else:
                groups.append((current_start, current_end - current_start + 1))
                current_start = addr
                current_end = addr
                
        groups.append((current_start, current_end - current_start + 1))
        
        return groups
        
    def _create_battery_data(self, values: Dict[str, Any]) -> Optional[BatteryData]:
        """Create BatteryData object from processed values."""
        try:
            return BatteryData(
                voltage=values.get("battery_voltage"),
                current=values.get("battery_current"),
                power=values.get("battery_power"),
                soc=values.get("battery_soc"),
                temperature=values.get("battery_temperature")
            )
        except (TypeError, KeyError) as e:
            logger.warning(f"Failed to create BatteryData, missing key: {e}")
        return None
        
    def _create_pv_data(self, values: Dict[str, Any]) -> Optional[PVData]:
        """Create PVData object from processed values."""
        try:
            return PVData(
                total_power=values.get("pv_total_power"),
                charging_power=values.get("pv_charging_power"),
                charging_current=values.get("pv_charging_current"),
                temperature=values.get("pv_temperature"),
                pv1_voltage=values.get("pv1_voltage"),
                pv1_current=values.get("pv1_current"),
                pv1_power=values.get("pv1_power"),
                pv2_voltage=values.get("pv2_voltage"),
                pv2_current=values.get("pv2_current"),
                pv2_power=values.get("pv2_power"),
                pv_generated_today=values.get("pv_energy_today"),
                pv_generated_total=values.get("pv_energy_total")
            )
        except (TypeError, KeyError) as e:
            logger.warning(f"Failed to create PVData, missing key: {e}")
        return None
        
    def _create_grid_data(self, values: Dict[str, Any]) -> Optional[GridData]:
        """Create GridData object from processed values."""
        try:
            return GridData(
                voltage=values.get("grid_voltage"),
                power=values.get("grid_power"),
                frequency=values.get("grid_frequency")
            )
        except (TypeError, KeyError) as e:
            logger.warning(f"Failed to create GridData, missing key: {e}")
        return None
        
    def _create_output_data(self, values: Dict[str, Any]) -> Optional[OutputData]:
        """Create OutputData object from processed values."""
        try:
            return OutputData(
                voltage=values.get("output_voltage"),
                current=values.get("output_current"),
                power=values.get("output_power"),
                apparent_power=values.get("output_apparent_power"),
                load_percentage=values.get("output_load_percentage"),
                frequency=values.get("output_frequency")
            )
        except (TypeError, KeyError) as e:
            logger.warning(f"Failed to create OutputData, missing key: {e}")
        return None
        
    def _create_system_status(self, values: Dict[str, Any]) -> Optional[SystemStatus]:
        """Create SystemStatus object from processed values."""
        inverter_timestamp = None
        if all(f"time_register_{i}" in values for i in range(6)):
            try:
                inverter_timestamp = datetime.datetime(
                    values["time_register_0"], values["time_register_1"], values["time_register_2"],
                    values["time_register_3"], values["time_register_4"], values["time_register_5"]
                )
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"Failed to create timestamp: {e}")

        op_mode = None
        mode_name = "UNKNOWN"
        if "operation_mode" in values:
            mode_value = values["operation_mode"]
            try:
                op_mode = OperatingMode(mode_value)
                mode_name = op_mode.name
            except ValueError:
                mode_name = f"UNKNOWN ({mode_value})"

        return SystemStatus(
            operating_mode=op_mode,
            mode_name=mode_name,
            inverter_time=inverter_timestamp
        )
