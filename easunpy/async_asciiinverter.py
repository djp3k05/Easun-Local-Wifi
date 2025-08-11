# easunpy/async_asciiinverter.py
# Implements the high-level logic for the Voltronic ASCII inverter.

import asyncio
import logging
from typing import Optional, Tuple, Dict, Any

from .async_asciiclient import AsyncAsciiClient
from .models import BatteryData, PVData, GridData, OutputData, SystemStatus, OperatingMode
from .async_ascii_commands import parse_qpgis, parse_qmod

logger = logging.getLogger(__name__)

class AsyncAsciiInverter:
    """
    High-level class to interact with a Voltronic ASCII inverter.
    """
    def __init__(self, inverter_ip: str, local_ip: str):
        self.client = AsyncAsciiClient(inverter_ip=inverter_ip, local_ip=local_ip)
        self.model = "VOLTRONIC_ASCII"

    async def get_all_data(self) -> Tuple[Optional[BatteryData], Optional[PVData], Optional[GridData], Optional[OutputData], Optional[SystemStatus]]:
        """
        Fetches all data from the inverter by sending ASCII commands sequentially.
        """
        await self.client.ensure_connection()

        if not self.client.is_connected():
            logger.info("Inverter is not connected yet. Waiting for connection on the next update cycle.")
            return None, None, None, None, None

        try:
            # Run commands sequentially to avoid race conditions
            qpgis_res = await self.client.send_command("QPIGS")
            await asyncio.sleep(0.5) # Small delay between commands
            qmod_res = await self.client.send_command("QMOD")

            qpgis_data = parse_qpgis(qpgis_res)
            op_mode = parse_qmod(qmod_res)

            if not qpgis_data:
                logger.warning("Parsing QPIGS data resulted in an empty dictionary.")
                return None, None, None, None, None

            battery = BatteryData(
                voltage=qpgis_data.get('battery_voltage', 0.0),
                power=int(qpgis_data.get('battery_voltage', 0.0) * (qpgis_data.get('battery_charging_current', 0) - qpgis_data.get('battery_discharge_current', 0))),
                current=float(qpgis_data.get('battery_charging_current', 0) - qpgis_data.get('battery_discharge_current', 0)),
                soc=qpgis_data.get('battery_soc', 0),
                temperature=qpgis_data.get('inverter_temperature', 0)
            )

            pv = PVData(
                total_power=qpgis_data.get('pv_charging_power', 0),
                charging_power=qpgis_data.get('pv_charging_power', 0),
                charging_current=float(qpgis_data.get('pv1_current', 0.0)),
                temperature=qpgis_data.get('inverter_temperature', 0),
                pv1_voltage=float(qpgis_data.get('pv1_voltage', 0.0)),
                pv1_current=float(qpgis_data.get('pv1_current', 0.0)),
                pv1_power=int(float(qpgis_data.get('pv1_voltage', 0.0)) * float(qpgis_data.get('pv1_current', 0.0))),
                pv2_voltage=0.0,
                pv2_current=0.0,
                pv2_power=0,
                pv_generated_today=0.0,
                pv_generated_total=0.0,
            )
            
            grid = GridData(
                voltage=qpgis_data.get('grid_voltage', 0.0),
                power=0,
                frequency=int(qpgis_data.get('grid_frequency', 0.0) * 100),
            )

            output = OutputData(
                voltage=qpgis_data.get('output_voltage', 0.0),
                current=0.0,
                power=qpgis_data.get('output_power', 0),
                apparent_power=qpgis_data.get('output_apparent_power', 0),
                load_percentage=qpgis_data.get('output_load_percentage', 0),
                frequency=int(qpgis_data.get('output_frequency', 0.0) * 100),
            )

            status = SystemStatus(
                operating_mode=op_mode,
                mode_name=op_mode.name if op_mode else "UNKNOWN",
                inverter_time=None
            )

            return battery, pv, grid, output, status

        except Exception as e:
            logger.error(f"Error getting all data for ASCII inverter: {e}")
            await self.client.disconnect()
            return None, None, None, None, None
            
    async def update_model(self, model: str):
        """Placeholder for model updates."""
        logger.debug(f"Model update called for ASCII inverter, but it only supports one model.")
        pass
