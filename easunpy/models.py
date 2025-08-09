from dataclasses import dataclass, field
from enum import Enum
import datetime
from typing import Dict, Optional, Callable, Any

# ---------------------------------------------------------------------------
#                        runtime‑data containers
# ---------------------------------------------------------------------------

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
    """Common operating‑mode codes across all Easun / Voltronic firmwares."""
    LINE  = "L"   # utility / grid
    BAT   = "B"   # battery‑only
    SUB   = 2     # line‑solar‑battery (SMG‑II)
    SBU   = 3     # solar‑battery‑utility
    FAULT = 0xFF  # unknown / error

@dataclass
class SystemStatus:
    operating_mode: OperatingMode
    mode_name: str
    inverter_time: Optional[datetime.datetime] = None

# ---------------------------------------------------------------------------
#                       configuration helpers
# ---------------------------------------------------------------------------

@dataclass
class RegisterConfig:
    address: int
    scale_factor: float = 1.0
    processor: Optional[Callable[[int], Any]] = None

@dataclass
class ModelConfig:
    """
    A *model* description used by AsyncISolar.

    • ``register_map`` – only needed for Modbus models  
    • ``protocol``     – “modbus” | “pi17”
    """
    name: str
    register_map: Dict[str, RegisterConfig] = field(default_factory=dict)
    protocol: str = "modbus"          # default keeps legacy behaviour

    # ---------- convenience helpers ----------
    def get_address(self, register_name: str) -> Optional[int]:
        return self.register_map.get(register_name).address if register_name in self.register_map else None

    def get_scale_factor(self, register_name: str) -> float:
        return self.register_map.get(register_name).scale_factor if register_name in self.register_map else 1.0

    def process_value(self, register_name: str, value: int) -> Any:
        cfg = self.register_map.get(register_name)
        if not cfg:
            return value
        if cfg.processor:
            return cfg.processor(value)
        return value * cfg.scale_factor

# ---------------------------------------------------------------------------
#                           model definitions
# ---------------------------------------------------------------------------

# -- ISOLAR SMG‑II 11 kW (Modbus) ------------------------------------------
ISOLAR_SMG_II_11K = ModelConfig(
    name="ISOLAR_SMG_II_11K",
    protocol="modbus",
    register_map={
        "operation_mode": RegisterConfig(201),
        "battery_voltage": RegisterConfig(277, 0.1),
        "battery_current": RegisterConfig(278, 0.1),
        "battery_power":   RegisterConfig(279),
        "battery_soc":     RegisterConfig(280),
        "battery_temperature": RegisterConfig(281),

        "pv_total_power":       RegisterConfig(302),
        "pv_charging_power":    RegisterConfig(303),
        "pv_charging_current":  RegisterConfig(304, 0.1),
        "pv_temperature":       RegisterConfig(305),

        "pv1_voltage": RegisterConfig(351, 0.1),
        "pv1_current": RegisterConfig(352, 0.1),
        "pv1_power":   RegisterConfig(353),
        "pv2_voltage": RegisterConfig(389, 0.1),
        "pv2_current": RegisterConfig(390, 0.1),
        "pv2_power":   RegisterConfig(391),

        "grid_voltage":   RegisterConfig(338, 0.1),
        "grid_current":   RegisterConfig(339, 0.1),
        "grid_power":     RegisterConfig(340),
        "grid_frequency": RegisterConfig(607),

        "output_voltage":        RegisterConfig(346, 0.1),
        "output_current":        RegisterConfig(347, 0.1),
        "output_power":          RegisterConfig(348),
        "output_apparent_power": RegisterConfig(349),
        "output_load_percentage":RegisterConfig(350),
        "output_frequency":      RegisterConfig(607),

        # inverter RTC (YYYY‑MM‑DD HH:MM:SS)
        "time_register_0": RegisterConfig(696, processor=int),
        "time_register_1": RegisterConfig(697, processor=int),
        "time_register_2": RegisterConfig(698, processor=int),
        "time_register_3": RegisterConfig(699, processor=int),
        "time_register_4": RegisterConfig(700, processor=int),
        "time_register_5": RegisterConfig(701, processor=int),

        "pv_energy_today": RegisterConfig(702, 0.01),
        "pv_energy_total": RegisterConfig(703, 0.01),
    },
)

# -- ISOLAR SMG‑II 6 kW (Modbus) ------------------------------------------
ISOLAR_SMG_II_6K = ModelConfig(
    name="ISOLAR_SMG_II_6K",
    protocol="modbus",
    register_map={
        "operation_mode": RegisterConfig(201),
        "battery_voltage": RegisterConfig(215, 0.1),
        "battery_current": RegisterConfig(216, 0.1),
        "battery_power":   RegisterConfig(217),
        "battery_soc":     RegisterConfig(229),
        "battery_temperature": RegisterConfig(226),

        "pv_total_power":       RegisterConfig(223),
        "pv_charging_power":    RegisterConfig(224),
        "pv_charging_current":  RegisterConfig(234, 0.1),
        "pv_temperature":       RegisterConfig(227),

        "pv1_voltage": RegisterConfig(219, 0.1),
        "pv1_current": RegisterConfig(220, 0.1),
        "pv1_power":   RegisterConfig(223),

        "grid_voltage":   RegisterConfig(202, 0.1),
        "grid_power":     RegisterConfig(204),
        "grid_frequency": RegisterConfig(203),

        "output_voltage":        RegisterConfig(210, 0.1),
        "output_current":        RegisterConfig(211, 0.1),
        "output_power":          RegisterConfig(213),
        "output_apparent_power": RegisterConfig(214),
        "output_load_percentage":RegisterConfig(225, 0.01),
        "output_frequency":      RegisterConfig(212),

        # RTC (same offsets as 11 kW unit)
        "time_register_0": RegisterConfig(696, processor=int),
        "time_register_1": RegisterConfig(697, processor=int),
        "time_register_2": RegisterConfig(698, processor=int),
        "time_register_3": RegisterConfig(699, processor=int),
        "time_register_4": RegisterConfig(700, processor=int),
        "time_register_5": RegisterConfig(701, processor=int),
    },
)

# -- Easun SMW 8 / 11 kW (PI‑17 text protocol, no Modbus registers) --------
EASUN_SMW_8K = ModelConfig(
    name="EASUN_SMW_8K",
    protocol="pi17",     # <‑‑ tells AsyncISolar to use AsyncPIClient
    register_map={},     # register map unused for PI‑17
)

EASUN_SMW_11K = ModelConfig(
    name="EASUN_SMW_11K",
    protocol="pi17",
    register_map={},
)

# ---------------------------------------------------------------------------
#                   registry consumed by the rest of the code
# ---------------------------------------------------------------------------
MODEL_CONFIGS: Dict[str, ModelConfig] = {
    "ISOLAR_SMG_II_11K": ISOLAR_SMG_II_11K,
    "ISOLAR_SMG_II_6K":  ISOLAR_SMG_II_6K,
    "EASUN_SMW_8K":      EASUN_SMW_8K,
    "EASUN_SMW_11K":     EASUN_SMW_11K,
}

# ---------------------------------------------------------------------------
#              helper parsers used by the PI‑17 ASCII backend
# ---------------------------------------------------------------------------

def parse_qpiri_response(resp: str) -> dict:
    """Decode a raw QPIRI line into structured fields."""
    v = resp.strip("()\r").split()
    return {
        'grid_voltage_rating':       float(v[0]),
        'grid_current_rating':       float(v[1]),
        'output_voltage_rating':     float(v[2]),
        'output_frequency_rating':   float(v[3]),
        'output_current_rating':     float(v[4]),
        'output_power_rating':       int(v[5]),
        'output_va_rating':          int(v[6]),
        'battery_voltage_rating':    float(v[7]),
        'battery_recharge_voltage':  float(v[8]),
        'battery_under_voltage':     float(v[9]),
        'battery_bulk_voltage':      float(v[10]),
        'battery_float_voltage':     float(v[11]),
        'battery_type':              int(v[12]),
        'max_ac_charging_current':   int(v[13]),
        'max_charging_current':      int(v[14]),
        'input_voltage_range':       int(v[15]),
        'output_source_priority':    int(v[16]),
        'charger_source_priority':   int(v[17]),
        'parallel_max_num':          int(v[18]),
        'machine_type':              v[19],
        'topology':                  int(v[20]),
        'output_mode':               int(v[21]),
        'battery_redischarge_voltage': float(v[22]),
        'pv_ok_condition':           int(v[23]),
        'pv_power_balance':          int(v[24]),
        'max_pv_charging_current':   int(v[25]),
    }

def parse_qbeqi_response(resp: str) -> dict:
    v = resp.strip("()\r").split()
    return {
        'equalization_status':      int(v[0]),
        'equalization_time':        int(v[1]),
        'equalization_period':      int(v[2]),
        'max_equalization_time':    int(v[3]),
        'equalization_timeout':     int(v[4]),
        'battery_equalized_voltage':float(v[5]),
        'equalization_interval':    int(v[6]),
        'max_equalization_current': int(v[7]),
    }

def parse_qdop_response(resp: str) -> dict:
    v = resp.strip("()\r").split()
    return {
        'output_priority':             int(v[0]),
        'charger_priority':            int(v[1]),
        'battery_type':                int(v[2]),
        'buzzer':                      int(v[3]),
        'auto_return_display':         float(v[4]),
        'battery_bulk_charge_voltage': float(v[5]),
        'battery_capacity':            int(v[6]),
        'battery_recharge_voltage':    int(v[7]),
        'battery_under_voltage':       int(v[8]),
        'battery_cutoff_voltage':      int(v[9]),
        'battery_equalization':        int(v[12]),
        'equalization_time':           int(v[13]),
        'battery_float_charge_voltage':float(v[14]),
    }
