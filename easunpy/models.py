from dataclasses import dataclass, field
from enum import Enum
import datetime
from typing import Dict, Optional, Callable, Any

@dataclass
class BatteryData:
    voltage: float
    current: float
    power: int
    soc: int
    temperature: int

@dataclass
class PVData:
    total_power: int
    charging_power: int
    charging_current: int
    temperature: int
    pv1_voltage: float
    pv1_current: int
    pv1_power: int
    pv2_voltage: float
    pv2_current: int
    pv2_power: int
    pv_generated_today: int
    pv_generated_total: int

@dataclass
class GridData:
    voltage: float
    power: int
    frequency: int

@dataclass
class OutputData:
    voltage: float
    current: float
    power: int
    apparent_power: int
    load_percentage: int
    frequency: int

class OperatingMode(Enum):
    SUB = 2
    SBU = 3

@dataclass
class SystemStatus:
    operating_mode: OperatingMode
    mode_name: str 
    inverter_time: datetime.datetime

@dataclass
class RegisterConfig:
    """Configuration for a single register."""
    address: int
    scale_factor: float = 1.0  # Default scale factor is 1.0 (no scaling)
    processor: Optional[Callable[[int], Any]] = None  # Optional custom processor function

@dataclass
class ModelConfig:
    """Complete configuration for an inverter model."""
    name: str
    register_map: Dict[str, RegisterConfig] = field(default_factory=dict)
    
    # Helper method to get a register address
    def get_address(self, register_name: str) -> Optional[int]:
        config = self.register_map.get(register_name)
        return config.address if config else None
    
    # Helper method to get a register's scale factor
    def get_scale_factor(self, register_name: str) -> float:
        config = self.register_map.get(register_name)
        return config.scale_factor if config else 1.0
    
    # Helper method to process a register value
    def process_value(self, register_name: str, value: int) -> Any:
        config = self.register_map.get(register_name)
        if not config:
            return value
        
        # Apply custom processor if available
        if config.processor:
            return config.processor(value)
        
        # Otherwise apply scale factor
        return value * config.scale_factor

# Define model configurations
ISOLAR_SMG_II_11K = ModelConfig(
    name="ISOLAR_SMG_II_11K",
    register_map={
        "operation_mode": RegisterConfig(201),
        "battery_voltage": RegisterConfig(277, 0.1),
        "battery_current": RegisterConfig(278, 0.1),
        "battery_power": RegisterConfig(279),
        "battery_soc": RegisterConfig(280),
        "battery_temperature": RegisterConfig(281),
        "pv_total_power": RegisterConfig(302),
        "pv_charging_power": RegisterConfig(303),
        "pv_charging_current": RegisterConfig(304, 0.1),
        "pv_temperature": RegisterConfig(305),
        "pv1_voltage": RegisterConfig(351, 0.1),
        "pv1_current": RegisterConfig(352, 0.1),
        "pv1_power": RegisterConfig(353),
        "pv2_voltage": RegisterConfig(389, 0.1),
        "pv2_current": RegisterConfig(390, 0.1),
        "pv2_power": RegisterConfig(391),
        "grid_voltage": RegisterConfig(338, 0.1),
        "grid_current": RegisterConfig(339, 0.1),
        "grid_power": RegisterConfig(340),
        "grid_frequency": RegisterConfig(607),
        "output_voltage": RegisterConfig(346, 0.1),
        "output_current": RegisterConfig(347, 0.1),
        "output_power": RegisterConfig(348),
        "output_apparent_power": RegisterConfig(349),
        "output_load_percentage": RegisterConfig(350),
        "output_frequency": RegisterConfig(607),
        "time_register_0": RegisterConfig(696, processor=int),  # Year
        "time_register_1": RegisterConfig(697, processor=int),  # Month
        "time_register_2": RegisterConfig(698, processor=int),  # Day
        "time_register_3": RegisterConfig(699, processor=int),  # Hour
        "time_register_4": RegisterConfig(700, processor=int),  # Minute
        "time_register_5": RegisterConfig(701, processor=int),  # Second
        "pv_energy_today": RegisterConfig(702, 0.01),
        "pv_energy_total": RegisterConfig(703, 0.01),
    }
)

ISOLAR_SMG_II_6K = ModelConfig(
    name="ISOLAR_SMG_II_6K",
    register_map={
        "operation_mode": RegisterConfig(201),
        "battery_voltage": RegisterConfig(215, 0.1),
        "battery_current": RegisterConfig(216, 0.1),
        "battery_power": RegisterConfig(217),
        "battery_soc": RegisterConfig(229),
        "battery_temperature": RegisterConfig(226),  # Using DCDC temperature
        "pv_total_power": RegisterConfig(223),
        "pv_charging_power": RegisterConfig(224),
        "pv_charging_current": RegisterConfig(234, 0.1),
        "pv_temperature": RegisterConfig(227),  # Using inverter temperature
        "pv1_voltage": RegisterConfig(219, 0.1),
        "pv1_current": RegisterConfig(220, 0.1),
        "pv1_power": RegisterConfig(223),
        "pv2_voltage": RegisterConfig(0),  # Not supported
        "pv2_current": RegisterConfig(0),  # Not supported
        "pv2_power": RegisterConfig(0),    # Not supported
        "grid_voltage": RegisterConfig(202, 0.1),
        "grid_current": RegisterConfig(0),  # Not available
        "grid_power": RegisterConfig(204),
        "grid_frequency": RegisterConfig(203),
        "output_voltage": RegisterConfig(210, 0.1),
        "output_current": RegisterConfig(211, 0.1),
        "output_power": RegisterConfig(213),
        "output_apparent_power": RegisterConfig(214),
        "output_load_percentage": RegisterConfig(225, 0.01),
        "output_frequency": RegisterConfig(212),
        "time_register_0": RegisterConfig(696, processor=int),  # Year
        "time_register_1": RegisterConfig(697, processor=int),  # Month
        "time_register_2": RegisterConfig(698, processor=int),  # Day
        "time_register_3": RegisterConfig(699, processor=int),  # Hour
        "time_register_4": RegisterConfig(700, processor=int),  # Minute
        "time_register_5": RegisterConfig(701, processor=int),  # Second
        "pv_energy_today": RegisterConfig(0),  # Not supported
        "pv_energy_total": RegisterConfig(0),  # Not supported
    }
)

# EASUN SMW 8kW and 11kW configuration (same registers)
# Based on PCAP analysis showing QPIRI, QLED, QBEQI, QDOP commands
EASUN_SMW_8K = ModelConfig(
    name="EASUN_SMW_8K",
    register_map={
        # Operating mode from QLED response
        "operation_mode": RegisterConfig(201),  # From QLED: position indicates mode
        
        # Battery parameters - from QBEQI response
        # QBEQI response: (0 060 030 150 030 58.40 224 120 0 0000)
        "battery_voltage": RegisterConfig(280, 0.1),  # From QBEQI: 58.40V
        "battery_current": RegisterConfig(281, 0.1),  # Calculated from power/voltage
        "battery_power": RegisterConfig(282),  # Calculated value
        "battery_soc": RegisterConfig(283),  # State of charge percentage
        "battery_temperature": RegisterConfig(284),  # Battery temperature
        
        # PV parameters - from QPIRI and status
        "pv_total_power": RegisterConfig(302),  # Total PV power
        "pv_charging_power": RegisterConfig(303),  # PV charging power
        "pv_charging_current": RegisterConfig(304, 0.1),  # PV charging current
        "pv_temperature": RegisterConfig(305),  # PV/Inverter temperature
        
        # PV1 parameters
        "pv1_voltage": RegisterConfig(351, 0.1),  
        "pv1_current": RegisterConfig(352, 0.1),  
        "pv1_power": RegisterConfig(353),
        
        # PV2 parameters (if dual MPPT)
        "pv2_voltage": RegisterConfig(389, 0.1),
        "pv2_current": RegisterConfig(390, 0.1),
        "pv2_power": RegisterConfig(391),
        
        # Grid parameters - from QPIRI response
        # QPIRI: (230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 48.0 47.0 56.4 54.0 ...)
        "grid_voltage": RegisterConfig(338, 0.1),  # Grid voltage: 230.0V
        "grid_current": RegisterConfig(339, 0.1),  # Grid current
        "grid_power": RegisterConfig(340),  # Grid power
        "grid_frequency": RegisterConfig(341, 0.01),  # Grid frequency: 50.0Hz
        
        # Output parameters - from QPIRI response
        "output_voltage": RegisterConfig(346, 0.1),  # Output voltage: 230.0V
        "output_current": RegisterConfig(347, 0.1),  # Output current: 47.8A
        "output_power": RegisterConfig(348),  # Output power: 11000W
        "output_apparent_power": RegisterConfig(349),  # Output VA: 11000VA
        "output_load_percentage": RegisterConfig(350),  # Load percentage
        "output_frequency": RegisterConfig(351, 0.01),  # Output frequency: 50.0Hz
        
        # Time registers (if supported)
        "time_register_0": RegisterConfig(696, processor=int),  # Year
        "time_register_1": RegisterConfig(697, processor=int),  # Month
        "time_register_2": RegisterConfig(698, processor=int),  # Day
        "time_register_3": RegisterConfig(699, processor=int),  # Hour
        "time_register_4": RegisterConfig(700, processor=int),  # Minute
        "time_register_5": RegisterConfig(701, processor=int),  # Second
        
        # Energy counters
        "pv_energy_today": RegisterConfig(702, 0.01),  # kWh generated today
        "pv_energy_total": RegisterConfig(703, 0.01),  # Total kWh generated
    }
)

# EASUN SMW 11kW uses the same configuration as 8kW
EASUN_SMW_11K = ModelConfig(
    name="EASUN_SMW_11K",
    register_map=EASUN_SMW_8K.register_map.copy()  # Same as 8kW model
)

# Dictionary of all supported models
MODEL_CONFIGS = {
    "ISOLAR_SMG_II_11K": ISOLAR_SMG_II_11K,
    "ISOLAR_SMG_II_6K": ISOLAR_SMG_II_6K,
    "EASUN_SMW_8K": EASUN_SMW_8K,
    "EASUN_SMW_11K": EASUN_SMW_11K,
}

# Helper function to parse QPIRI response
def parse_qpiri_response(response: str) -> dict:
    """
    Parse QPIRI response string.
    Example: (230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 48.0 47.0 56.4 54.0 2 010 150 0 2 3 6 01 0 0 54.0 0 1 480 0 000)
    """
    values = response.strip('()').split()
    return {
        'grid_voltage_rating': float(values[0]),
        'grid_current_rating': float(values[1]),
        'output_voltage_rating': float(values[2]),
        'output_frequency_rating': float(values[3]),
        'output_current_rating': float(values[4]),
        'output_power_rating': int(values[5]),
        'output_va_rating': int(values[6]),
        'battery_voltage_rating': float(values[7]),
        'battery_recharge_voltage': float(values[8]),
        'battery_under_voltage': float(values[9]),
        'battery_bulk_voltage': float(values[10]),
        'battery_float_voltage': float(values[11]),
        'battery_type': int(values[12]),
        'max_ac_charging_current': int(values[13]),
        'max_charging_current': int(values[14]),
        'input_voltage_range': int(values[15]),
        'output_source_priority': int(values[16]),
        'charger_source_priority': int(values[17]),
        'parallel_max_num': int(values[18]),
        'machine_type': values[19],
        'topology': int(values[20]),
        'output_mode': int(values[21]),
        'battery_redischarge_voltage': float(values[22]),
        'pv_ok_condition': int(values[23]),
        'pv_power_balance': int(values[24]),
        'max_pv_charging_current': int(values[25]),
    }

# Helper function to parse QBEQI response
def parse_qbeqi_response(response: str) -> dict:
    """
    Parse QBEQI response string.
    Example: (0 060 030 150 030 58.40 224 120 0 0000)
    """
    values = response.strip('()').split()
    return {
        'equalization_status': int(values[0]),
        'equalization_time': int(values[1]),
        'equalization_period': int(values[2]),
        'max_equalization_time': int(values[3]),
        'equalization_timeout': int(values[4]),
        'battery_equalized_voltage': float(values[5]),
        'equalization_interval': int(values[6]),
        'max_equalization_current': int(values[7]),
        'reserved': int(values[8]),
        'checksum': values[9],
    }

# Helper function to parse QDOP response
def parse_qdop_response(response: str) -> dict:
    """
    Parse QDOP response string.
    Example: (1 3 2 0 00.0 48.0 999 40 010 080 000 000 00 23 46.0 000 0206)
    """
    values = response.strip('()').split()
    return {
        'output_priority': int(values[0]),
        'charger_priority': int(values[1]),
        'battery_type': int(values[2]),
        'buzzer': int(values[3]),
        'auto_return_display': float(values[4]),
        'battery_bulk_charge_voltage': float(values[5]),
        'battery_capacity': int(values[6]),
        'battery_recharge_voltage': int(values[7]),
        'battery_under_voltage': int(values[8]),
        'battery_cutoff_voltage': int(values[9]),
        'reserved1': int(values[10]),
        'reserved2': int(values[11]),
        'battery_equalization': int(values[12]),
        'equalization_time': int(values[13]),
        'battery_float_charge_voltage': float(values[14]),
        'reserved3': int(values[15]),
        'checksum': values[16],
    }
