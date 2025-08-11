# easunpy/async_asciiinverter.py
# Implements the high-level logic for the Voltronic ASCII inverter.

import logging
from typing import Optional, Tuple, Dict, Any

from .async_asciiclient import AsyncAsciiClient
from .models import BatteryData, PVData, GridData, OutputData, SystemStatus, OperatingMode

logger = logging.getLogger(__name__)

class AsyncAsciiInverter:
    """
    High-level class to interact with a Voltronic ASCII inverter.
    """
    def __init__(self, inverter_ip: str, local_ip: str):
        self.client = AsyncAsciiClient(inverter_ip=inverter_ip, local_ip=local_ip)
        self.model = "VOLTRONIC_ASCII"

    def _parse_qpgis(self, raw: str) -> Dict[str, Any]:
        """Parses the response from the QPIGS command."""
        try:
            fields = raw.strip('(').split(' ')
            if len(fields) < 21:
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

    def _parse_qmod(self, raw: str) -> Optional[OperatingMode]:
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

    async def get_all_data(self) -> Tuple[Optional[BatteryData], Optional[PVData], Optional[GridData], Optional[OutputData], Optional[SystemStatus]]:
        """
        Fetches all data from the inverter by sending multiple ASCII commands.
        """
        try:
            # Send all commands concurrently
            tasks = {
                "qpgis": self.client.send_command("QPIGS"),
                "qmod": self.client.send_command("QMOD"),
            }
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            
            # Check for errors
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    cmd = list(tasks.keys())[i]
                    logger.error(f"Error executing command {cmd}: {res}")
                    # Disconnect to force a reconnect on the next attempt
                    await self.client.disconnect()
                    return None, None, None, None, None

            qpgis_res, qmod_res = results
            
            qpgis_data = self._parse_qpgis(qpgis_res)
            op_mode = self._parse_qmod(qmod_res)

            if not qpgis_data:
                return None, None, None, None, None

            battery = BatteryData(
                voltage=qpgis_data.get('battery_voltage', 0.0),
                # Power is calculated: voltage * (charge_current - discharge_current)
                power=int(qpgis_data.get('battery_voltage', 0.0) * (qpgis_data.get('battery_charging_current', 0) - qpgis_data.get('battery_discharge_current', 0))),
                current=float(qpgis_data.get('battery_charging_current', 0) - qpgis_data.get('battery_discharge_current', 0)),
                soc=qpgis_data.get('battery_soc', 0),
                temperature=qpgis_data.get('inverter_temperature', 0) # Using inverter temp as battery temp
            )

            pv = PVData(
                total_power=qpgis_data.get('pv_charging_power', 0),
                charging_power=qpgis_data.get('pv_charging_power', 0),
                charging_current=float(qpgis_data.get('pv1_current', 0.0)),
                temperature=qpgis_data.get('inverter_temperature', 0),
                pv1_voltage=qpgis_data.get('pv1_voltage', 0.0),
                pv1_current=qpgis_data.get('pv1_current', 0.0),
                pv1_power=int(qpgis_data.get('pv1_voltage', 0.0) * qpgis_data.get('pv1_current', 0.0)),
                # This inverter model does not seem to support PV2 or energy generation stats
                pv2_voltage=0.0,
                pv2_current=0.0,
                pv2_power=0,
                pv_generated_today=0,
                pv_generated_total=0,
            )
            
            grid = GridData(
                voltage=qpgis_data.get('grid_voltage', 0.0),
                power=0, # QPIGS does not provide grid power directly
                frequency=int(qpgis_data.get('grid_frequency', 0.0) * 100),
            )

            output = OutputData(
                voltage=qpgis_data.get('output_voltage', 0.0),
                current=0.0, # Not provided directly
                power=qpgis_data.get('output_power', 0),
                apparent_power=qpgis_data.get('output_apparent_power', 0),
                load_percentage=qpgis_data.get('output_load_percentage', 0),
                frequency=int(qpgis_data.get('output_frequency', 0.0) * 100),
            )

            status = SystemStatus(
                operating_mode=op_mode,
                mode_name=op_mode.name if op_mode else "UNKNOWN",
                inverter_time=None # Not provided by this inverter
            )

            return battery, pv, grid, output, status

        except Exception as e:
            logger.error(f"Error getting all data from ASCII inverter: {e}")
            await self.client.disconnect() # Force reconnect on next poll
            return None, None, None, None, None
            
    async def update_model(self, model: str):
        """Placeholder for model updates, not applicable for this class."""
        logger.debug(f"Model update called for ASCII inverter, but it only supports one model.")
        pass
