# async_isolar.py
import logging
from typing import List, Optional, Dict, Tuple, Any
from .async_modbusclient import AsyncModbusClient
from .modbusclient import create_request, decode_modbus_response
from .isolar import BatteryData, PVData, GridData, OutputData, SystemStatus, OperatingMode
import datetime
from .models import MODEL_CONFIGS, ModelConfig, ProtocolType
from enum import Enum

# Set up logging
logger = logging.getLogger(__name__)

class AsyncISolar:
    def __init__(self, inverter_ip: str, local_ip: str, model: str = "ISOLAR_SMG_II_11K"):
        self.client = AsyncModbusClient(inverter_ip=inverter_ip, local_ip=local_ip)
        self._transaction_id = 0x0772
        
        if model not in MODEL_CONFIGS:
            raise ValueError(f"Unknown inverter model: {model}. Available models: {list(MODEL_CONFIGS.keys())}")
        
        self.model = model
        self.model_config = MODEL_CONFIGS[model]
        logger.warning(f"AsyncISolar initialized with model: {model}")

    def update_model(self, model: str):
        """Update the model configuration."""
        if model not in MODEL_CONFIGS:
            raise ValueError(f"Unknown inverter model: {model}. Available models: {list(MODEL_CONFIGS.keys())}")
        
        logger.warning(f"Updating AsyncISolar to model: {model}")
        self.model = model
        self.model_config = MODEL_CONFIGS[model]

    def _get_next_transaction_id(self) -> int:
        """Get next transaction ID and increment counter."""
        current_id = self._transaction_id
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF  # Wrap around at 0xFFFF
        return current_id

    async def _read_registers_bulk(self, register_groups: list[tuple[int, int]], data_format: str = "Int") -> list[Optional[list[int]]]:
        """Read multiple groups of registers in a single connection."""
        try:
            # Create requests for each register group
            requests = [
                create_request(self._get_next_transaction_id(), 0x0001, unit_id=0x00, function_code=0x03, register_address=start, register_count=count)
                for start, count in register_groups
            ]
            
            logger.debug(f"Sending bulk request for register groups: {register_groups}")
            responses = await self.client.send_bulk(requests)
             
            # Initialize results array with None values
            decoded_groups = [None] * len(register_groups)
            
            # Process each response individually
            for i, (response, (_, count)) in enumerate(zip(responses, register_groups)):
                try:
                    if response:  # Only decode if we got a response
                        decoded = decode_modbus_response(response, count, data_format)
                        logger.debug(f"Decoded values for group {i}: {decoded}")
                        decoded_groups[i] = decoded
                    else:
                        logger.warning(f"No response for register group {register_groups[i]}")
                except Exception as e:
                    logger.warning(f"Failed to decode register group {register_groups[i]}: {e}")
                    # Keep None for this group
                
            return decoded_groups
            
        except Exception as e:
            logger.error(f"Error reading register groups: {str(e)}")
            return [None] * len(register_groups)

    async def _query_ascii_commands(self, commands: list[str]) -> Dict[str, str]:
        responses_dict = {}
        hex_commands = []
        for cmd in commands:
            packet = create_request(self._get_next_transaction_id(), ascii_command=cmd)
            hex_commands.append(packet)

        raw_responses = await self.client.send_bulk(hex_commands)

        for cmd, raw_resp in zip(commands, raw_responses):
            if raw_resp:
                parsed = decode_modbus_response(raw_resp, is_ascii=True)
                if isinstance(parsed, str) and parsed.startswith('('):
                    responses_dict[cmd] = parsed
                else:
                    logger.warning(f"Invalid ASCII response for {cmd}: {parsed}")
            else:
                logger.warning(f"No response for command {cmd}")

        return responses_dict

    def _parse_ascii_responses(self, responses: Dict[str, str]) -> Dict[str, Any]:
        values = {}

        # Parse QPIGS
        qpigs = responses.get('QPIGS')
        if qpigs:
            fields = qpigs[1:].split()  # Remove '(' and split
            if len(fields) >= 21:
                values['grid_voltage'] = float(fields[0])
                values['grid_frequency'] = float(fields[1]) 
                values['output_voltage'] = float(fields[2])
                values['output_frequency'] = float(fields[3]) 
                values['output_apparent_power'] = int(fields[4])
                values['output_power'] = int(fields[5])
                values['output_load_percentage'] = int(fields[6])
                values['battery_voltage'] = float(fields[8])
                values['battery_charging_current'] = int(fields[9])
                values['battery_soc'] = int(fields[10])
                values['pv1_current'] = float(fields[12])
                values['pv1_voltage'] = float(fields[13])
                values['battery_discharge_current'] = int(fields[15])
                values['pv1_power'] = int(fields[19])  # PV charging power

                # Calculate currents
                output_voltage = values['output_voltage']
                if output_voltage > 0:
                    values['output_current'] = values['output_apparent_power'] / output_voltage
                else:
                    values['output_current'] = 0.0

                grid_voltage = values['grid_voltage']
                if grid_voltage > 0:
                    values['grid_power'] = 0  # Need to map, but no direct grid power in QPIGS
                    # Assume grid power is 0 if in battery mode, or calculate if possible

        # Parse QPIGS2 for PV2
        qpigs2 = responses.get('QPIGS2')
        if qpigs2:
            fields = qpigs2[1:].split()
            if len(fields) >= 3:
                values['pv2_current'] = float(fields[0])
                values['pv2_voltage'] = float(fields[1])
                values['pv2_power'] = int(fields[2])

                # Update total power
                pv1_power = values.get('pv1_power', 0)
                values['pv_total_power'] = pv1_power + values['pv2_power']

        # Parse QMOD for mode
        qmod = responses.get('QMOD')
        if qmod:
            mode_char = qmod[1]
            if mode_char == 'L':
                values['operation_mode'] = 2  # SUB - Line mode
            elif mode_char == 'B':
                values['operation_mode'] = 3  # SBU - Battery mode
            elif mode_char == 'F':
                values['operation_mode'] = 1  # Fault, but adjust
            else:
                values['operation_mode'] = 0  # Unknown

        # Parse QPIWS if needed, but not used in data objects

        # Frequencies *100 for internal format
        if 'grid_frequency' in values:
            values['grid_frequency'] = int(values['grid_frequency'] * 100)
        if 'output_frequency' in values:
            values['output_frequency'] = int(values['output_frequency'] * 100)

        # Set missing to None or 0
        values.setdefault('battery_temperature', 0)
        values.setdefault('pv_temperature', 0)
        values.setdefault('grid_current', 0.0)
        values.setdefault('pv_charging_power', values.get('pv1_power', 0))
        values.setdefault('pv_charging_current', values.get('pv1_current', 0.0))
        values.setdefault('pv_generated_today', None)
        values.setdefault('pv_generated_total', None)

        return values

    async def get_all_data(self) -> tuple[Optional[BatteryData], Optional[PVData], Optional[GridData], Optional[OutputData], Optional[SystemStatus]]:
        """Get all inverter data in a single bulk request."""
        logger.warning(f"Getting all data for model: {self.model}")
        
        if self.model_config.protocol == ProtocolType.ASCII:
            command_responses = await self._query_ascii_commands(self.model_config.command_map)
            values = self._parse_ascii_responses(command_responses)
        else:
            # Original numerical logic
            register_groups = self._create_register_groups()
            
            results = await self._read_registers_bulk(register_groups)
            if not results:
                return None, None, None, None, None
                
            # Create a dictionary to store all the read values
            values = {}
            
            # Process the results and apply scaling factors
            for i, (start_address, count) in enumerate(register_groups):
                if results[i] is None:
                    continue
                    
                # Find which registers these values correspond to
                for reg_name, config in self.model_config.register_map.items():
                    if config.address >= start_address and config.address < start_address + count:
                        # Calculate the index in the results array
                        idx = config.address - start_address
                        if idx < len(results[i]):
                            # Process the value with the appropriate scaling factor
                            values[reg_name] = self.model_config.process_value(reg_name, results[i][idx])
        
        # Create data objects from the processed values
        battery = self._create_battery_data(values)
        pv = self._create_pv_data(values)
        grid = self._create_grid_data(values)
        output = self._create_output_data(values)
        status = self._create_system_status(values)
        
        return battery, pv, grid, output, status
        
    def _create_register_groups(self) -> list[tuple[int, int]]:
        """Create optimized register groups for reading."""
        # Get all valid register addresses
        addresses = [
            config.address for config in self.model_config.register_map.values() 
            if config.address > 0  # Skip registers with address 0 (not supported)
        ]
        
        if not addresses:
            return []
            
        # Sort addresses
        addresses.sort()
        
        groups = []
        current_start = addresses[0]
        current_end = addresses[0]
        
        for addr in addresses[1:]:
            # If address is consecutive or close enough, extend the current group
            if addr <= current_end + 10:  # Allow small gaps to reduce number of requests
                current_end = addr
            else:
                # Add the current group and start a new one
                groups.append((current_start, current_end - current_start + 1))
                current_start = addr
                current_end = addr
                
        # Add the last group
        groups.append((current_start, current_end - current_start + 1))
        
        return groups
        
    def _create_battery_data(self, values: Dict[str, Any]) -> Optional[BatteryData]:
        """Create BatteryData object from processed values."""
        try:
            if all(key in values for key in ["battery_voltage", "battery_current", "battery_power", "battery_soc", "battery_temperature"]):
                return BatteryData(
                    voltage=values["battery_voltage"],
                    current=values["battery_current"],
                    power=values["battery_power"],
                    soc=values["battery_soc"],
                    temperature=values["battery_temperature"]
                )
        except Exception as e:
            logger.warning(f"Failed to create BatteryData: {e}")
        return None
        
    def _create_pv_data(self, values: Dict[str, Any]) -> Optional[PVData]:
        """Create PVData object from processed values."""
        try:
            # Check if we have at least some PV data
            if any(key in values for key in ["pv_total_power", "pv1_voltage", "pv2_voltage"]):
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
                    pv_generated_today=values.get("pv_generated_today"),
                    pv_generated_total=values.get("pv_generated_total")
                )
        except Exception as e:
            logger.warning(f"Failed to create PVData: {e}")
        return None
        
    def _create_grid_data(self, values: Dict[str, Any]) -> Optional[GridData]:
        """Create GridData object from processed values."""
        try:
            if any(key in values for key in ["grid_voltage", "grid_power"]):
                return GridData(
                    voltage=values.get("grid_voltage"),
                    power=values.get("grid_power"),
                    frequency=values.get("grid_frequency")
                )
        except Exception as e:
            logger.warning(f"Failed to create GridData: {e}")
        return None
        
    def _create_output_data(self, values: Dict[str, Any]) -> Optional[OutputData]:
        """Create OutputData object from processed values."""
        try:
            if any(key in values for key in ["output_voltage", "output_power"]):
                return OutputData(
                    voltage=values.get("output_voltage"),
                    current=values.get("output_current"),
                    power=values.get("output_power"),
                    apparent_power=values.get("output_apparent_power"),
                    load_percentage=values.get("output_load_percentage"),
                    frequency=values.get("output_frequency")
                )
        except Exception as e:
            logger.warning(f"Failed to create OutputData: {e}")
        return None
        
    def _create_system_status(self, values: Dict[str, Any]) -> Optional[SystemStatus]:
        """Create SystemStatus object from processed values."""
        try:
            # Create timestamp if time registers are available
            inverter_timestamp = None
            if all(f"time_register_{i}" in values for i in range(6)):
                try:
                    year = values["time_register_0"]
                    month = values["time_register_1"]
                    day = values["time_register_2"]
                    hour = values["time_register_3"]
                    minute = values["time_register_4"]
                    second = values["time_register_5"]
                    inverter_timestamp = datetime.datetime(year, month, day, hour, minute, second)
                except Exception as e:
                    logger.warning(f"Failed to create timestamp: {e}")

            # Create operating mode
            if "operation_mode" in values:
                mode_value = values["operation_mode"]
                try:
                    op_mode = OperatingMode(mode_value)
                    return SystemStatus(
                        operating_mode=op_mode,
                        mode_name=op_mode.name,
                        inverter_time=inverter_timestamp
                    )
                except ValueError:
                    return SystemStatus(
                        operating_mode=OperatingMode.FAULT,
                        mode_name=f"UNKNOWN ({mode_value})",
                        inverter_time=inverter_timestamp
                    )
        except Exception as e:
            logger.warning(f"Failed to create SystemStatus: {e}")
        return None 
