# easunpy/models.py
from dataclasses import dataclass, field
from enum import Enum
import datetime
from typing import Dict, Optional, Callable, Any, List

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
    charging_current: float
    temperature: int
    pv1_voltage: float
    pv1_current: float
    pv1_power: int
    pv2_voltage: float
    pv2_current: float
    pv2_power: int
    pv_generated_today: float
    pv_generated_total: float

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

@dataclass
class RatingData:
    """Holds static rating data from the QPIRI command."""
    ac_output_rating_voltage: float
    ac_output_rating_frequency: float
    ac_output_rating_current: float
    ac_output_rating_apparent_power: int
    ac_output_rating_active_power: int
    battery_rating_voltage: float
    battery_recharge_voltage: float
    battery_under_voltage: float
    battery_bulk_voltage: float
    battery_float_voltage: float
    battery_type: str
    max_ac_charging_current: int
    max_charging_current: int
    output_source_priority: str
    charger_source_priority: str

class OperatingMode(Enum):
    SUB = 2; SBU = 3 # Modbus
    POWER_ON = 10; STANDBY = 11; LINE = 12; BATTERY = 13; FAULT = 14; POWER_SAVING = 15 # ASCII
    UNKNOWN = 99

@dataclass
class SystemStatus:
    operating_mode: Optional[OperatingMode]
    mode_name: str
    warnings: List[str]
    inverter_time: Optional[datetime.datetime]

# --- Below is for Modbus models, unchanged ---
@dataclass
class RegisterConfig:
    address: int
    scale_factor: float = 1.0
    processor: Optional[Callable[[int], Any]] = None

@dataclass
class ModelConfig:
    name: str
    protocol: str = "modbus"
    register_map: Dict[str, RegisterConfig] = field(default_factory=dict)
    # ... (rest of the class is unchanged)

# --- Model Definitions ---
VOLTRONIC_ASCII = ModelConfig(name="VOLTRONIC_ASCII", protocol="ascii")
ISOLAR_SMG_II_11K = ModelConfig(
    name="ISOLAR_SMG_II_11K",
    protocol="modbus",
    register_map={
        "operation_mode": RegisterConfig(201),
        "battery_voltage": RegisterConfig(277, 0.1),
        # ... (rest of the registers are unchanged)
    }
)
ISOLAR_SMG_II_6K = ModelConfig(
    name="ISOLAR_SMG_II_6K",
    protocol="modbus",
    register_map={
        "operation_mode": RegisterConfig(201),
        "battery_voltage": RegisterConfig(215, 0.1),
        # ... (rest of the registers are unchanged)
    }
)

MODEL_CONFIGS = {
    "VOLTRONIC_ASCII": VOLTRONIC_ASCII,
    "ISOLAR_SMG_II_11K": ISOLAR_SMG_II_11K,
    "ISOLAR_SMG_II_6K": ISOLAR_SMG_II_6K,
}
