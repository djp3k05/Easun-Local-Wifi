# easunpy/async_ascii_commands.py
# This file will define the commands and their parsers for the ASCII protocol.
# This helps separate the command logic from the connection logic.

import logging
from typing import Dict, Any, Optional
from .models import OperatingMode

logger = logging.getLogger(__name__)

def parse_qpgis(raw: str) -> Dict[str, Any]:
    """Parses the response from the QPIGS command."""
    try:
        fields = raw.strip('(').split(' ')
        if len(fields) < 21:
            logger.warning(f"QPIGS response has fewer than 21 fields: {raw}")
            return {}
        return {
            'grid_voltage': float(fields[0]),
            'grid_frequency': float(fields[1]),
            'output_voltage': float(fields[2]),
            'output_frequency': float(fields[3]),
            'output_apparent_power': int(fields[4]),
            'output_power': int(fields[5]),
            'output_load_percentage': int(fields[6]),
            'battery_voltage': float(fields[8]),
            'battery_charging_current': int(fields[9]),
            'battery_soc': int(fields[10]),
            'inverter_temperature': int(fields[11]),
            'pv1_current': float(fields[12]),
            'pv1_voltage': float(fields[13]),
            'battery_discharge_current': int(fields[15]),
            'pv_charging_power': int(fields[19]),
        }
    except (ValueError, IndexError) as e:
        logger.error(f"Failed to parse QPIGS response '{raw}': {e}")
        return {}

def parse_qmod(raw: str) -> Optional[OperatingMode]:
    """Parses the response from the QMOD command."""
    mode_char = raw.strip('(')
    mode_map = {
        'P': OperatingMode.POWER_ON,
        'S': OperatingMode.STANDBY,
        'L': OperatingMode.LINE,
        'B': OperatingMode.BATTERY,
        'F': OperatingMode.FAULT,
        'H': OperatingMode.POWER_SAVING,
    }
    return mode_map.get(mode_char)
