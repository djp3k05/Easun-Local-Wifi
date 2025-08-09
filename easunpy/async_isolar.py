"""
async_isolar.py – unified driver for Easun/Voltronic inverters

* Modbus‑TCP models (ISOLAR_SMG_II 6 kW / 11 kW …) use AsyncModbusClient
* PI‑17 ASCII models (EASUN_SMW 8 kW / 11 kW) use AsyncPIClient

Public surface stays compatible:  `get_all_data()` still returns
(BatteryData, PVData, GridData, OutputData, SystemStatus)
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from .async_modbusclient import AsyncModbusClient
from .async_piclient import AsyncPIClient           # ←   new
from .modbusclient import create_request, decode_modbus_response
from .isolar import (
    BatteryData,
    PVData,
    GridData,
    OutputData,
    SystemStatus,
    OperatingMode,
)
from .models import MODEL_CONFIGS, ModelConfig

# ---------- globals ----------
logger = logging.getLogger(__name__)


# ---------- main class ----------
class AsyncISolar:
    """High‑level asynchronous interface to an Easun / Voltronic inverter."""

    # ------------------------------------------------------------------ init
    def __init__(
        self,
        inverter_ip: str,
        local_ip: str,
        model: str = "ISOLAR_SMG_II_11K",
    ):
        if model not in MODEL_CONFIGS:
            raise ValueError(
                f"Unknown inverter model: {model}. "
                f"Available models: {list(MODEL_CONFIGS.keys())}"
            )

        self.model = model
        self.model_config: ModelConfig = MODEL_CONFIGS[model]

        # Detect protocol (absent → assume “modbus” for legacy models)
        protocol = getattr(self.model_config, "protocol", "modbus").lower()
        if protocol not in ("modbus", "pi17"):
            raise ValueError(f"Unsupported protocol “{protocol}” in model config")

        self.client = (
            AsyncPIClient(inverter_ip, local_ip)
            if protocol == "pi17"
            else AsyncModbusClient(inverter_ip, local_ip)
        )
        self._protocol = protocol
        self._transaction_id = 0x0772

        logger.info(
            "AsyncISolar initialised – model=%s, protocol=%s, inverter=%s",
            model,
            protocol,
            inverter_ip,
        )

    # ----------------------------------------------------- public helpers ---
    def update_model(self, model: str) -> None:
        """Switch to a different ModelConfig at runtime (options flow)."""
        if model not in MODEL_CONFIGS:
            raise ValueError(
                f"Unknown inverter model: {model}. "
                f"Available models: {list(MODEL_CONFIGS.keys())}"
            )

        self.model = model
        self.model_config = MODEL_CONFIGS[model]
        self._protocol = getattr(self.model_config, "protocol", "modbus").lower()

        # Re‑instantiate the appropriate client if protocol changed
        if self._protocol == "pi17" and not isinstance(self.client, AsyncPIClient):
            self.client = AsyncPIClient(self.client.inverter_ip, self.client.local_ip)
        elif self._protocol == "modbus" and not isinstance(
            self.client, AsyncModbusClient
        ):
            self.client = AsyncModbusClient(self.client.inverter_ip, self.client.local_ip)

        logger.info("AsyncISolar switched to model=%s, protocol=%s", model, self._protocol)

    # ---------------------------------------------------- transaction id ---
    def _get_next_transaction_id(self) -> int:
        tid = self._transaction_id
        self._transaction_id = (tid + 1) & 0xFFFF
        return tid

    # ============================================================= PUBLIC ==
    async def get_all_data(
        self,
    ) -> Tuple[
        Optional[BatteryData],
        Optional[PVData],
        Optional[GridData],
        Optional[OutputData],
        Optional[SystemStatus],
    ]:
        """Fetch every value needed by the HA integration in **one** call."""
        if self._protocol == "pi17":
            return await self._get_all_data_pi17()

        # fallback → Modbus
        return await self._get_all_data_modbus()

    # =========================================================== MODBUS ====
    # (code mostly identical to the original driver)
    async def _read_registers_bulk(
        self,
        register_groups: List[Tuple[int, int]],
        data_format: str = "Int",
    ) -> List[Optional[List[int]]]:
        """Internal helper for batched Modbus reads."""
        try:
            requests = [
                create_request(
                    self._get_next_transaction_id(),
                    0x0001,
                    0x00,
                    0x03,
                    start,
                    count,
                )
                for start, count in register_groups
            ]
            logger.debug("Bulk reading groups: %s", register_groups)
            raw_responses = await self.client.send_bulk(requests)
        except Exception as err:
            logger.error("Modbus bulk read error: %s", err)
            return [None] * len(register_groups)

        decoded: List[Optional[List[int]]] = [None] * len(register_groups)

        for i, (resp_hex, (_, count)) in enumerate(zip(raw_responses, register_groups)):
            try:
                if resp_hex:
                    decoded[i] = decode_modbus_response(resp_hex, count, data_format)
            except Exception as err:
                logger.warning("Failed to decode response %d: %s", i, err)

        return decoded

    def _create_register_groups(self) -> List[Tuple[int, int]]:
        """Optimise address list → fewest possible Modbus requests."""
        addrs = sorted(
            cfg.address
            for cfg in self.model_config.register_map.values()
            if cfg.address > 0
        )
        if not addrs:
            return []

        groups: List[Tuple[int, int]] = []
        start = end = addrs[0]

        for addr in addrs[1:]:
            if addr <= end + 10:  # allow small holes
                end = addr
            else:
                groups.append((start, end - start + 1))
                start = end = addr
        groups.append((start, end - start + 1))
        return groups

    async def _get_all_data_modbus(self):
        """Original Modbus implementation – untouched except for refactor."""
        groups = self._create_register_groups()
        results = await self._read_registers_bulk(groups)
        if not results:
            return (None, None, None, None, None)

        # Flatten into dict { register_name: processed_value }
        values: Dict[str, Any] = {}
        for grp_idx, (start, count) in enumerate(groups):
            if results[grp_idx] is None:
                continue
            for name, cfg in self.model_config.register_map.items():
                if start <= cfg.address < start + count:
                    idx = cfg.address - start
                    if idx < len(results[grp_idx]):
                        values[name] = self.model_config.process_value(
                            name, results[grp_idx][idx]
                        )

        return (
            self._create_battery_data(values),
            self._create_pv_data(values),
            self._create_grid_data(values),
            self._create_output_data(values),
            self._create_system_status(values),
        )

    # ============================================================= PI‑17 ===
    async def _get_all_data_pi17(self):
        """Gather data from an Easun SMW inverter via the PI‑17 ASCII protocol."""
        from .pi_parsers import (
            parse_qpigs,
            parse_qmod,
            parse_qbeqi,
            parse_qpiri,
        )

        cmds = ["QPIGS", "QMOD", "QBEQI", "QPIRI"]
        replies = await self.client.send_bulk(cmds)
        if len(replies) != len(cmds):
            logger.error("Missing PI‑17 replies – got %s", replies)
            return (None, None, None, None, None)

        r_qpigs = parse_qpigs(replies[0])
        mode_raw = parse_qmod(replies[1])
        _ = parse_qbeqi(replies[2])  # available if you need it elsewhere
        _ = parse_qpiri(replies[3])

        # -------------- Battery --------------
        batt_power = int(r_qpigs["battery_chg_current"] * r_qpigs["battery_voltage"])
        battery = BatteryData(
            voltage=r_qpigs["battery_voltage"],
            current=r_qpigs["battery_chg_current"],
            power=batt_power,
            soc=r_qpigs["battery_soc"],
            temperature=r_qpigs["inverter_temp"],
        )

        # -------------- PV -------------------
        pv = PVData(
            total_power=r_qpigs["pv_power"],
            charging_power=r_qpigs["pv_power"],
            charging_current=int(r_qpigs["pv_current"]),
            temperature=r_qpigs["inverter_temp"],
            pv1_voltage=r_qpigs["pv_voltage"],
            pv1_current=int(r_qpigs["pv_current"]),
            pv1_power=r_qpigs["pv_power"],
            pv2_voltage=0.0,
            pv2_current=0,
            pv2_power=0,
            pv_generated_today=0,
            pv_generated_total=0,
        )

        # -------------- Grid -----------------
        grid = GridData(
            voltage=r_qpigs["grid_voltage"],
            power=r_qpigs["output_active_pow"],
            frequency=int(r_qpigs["grid_frequency"] * 100),
        )

        # -------------- Output ---------------
        output = OutputData(
            voltage=r_qpigs["output_voltage"],
            current=0.0,
            power=r_qpigs["output_active_pow"],
            apparent_power=r_qpigs["output_apparent_pow"],
            load_percentage=r_qpigs["load_percent"],
            frequency=int(r_qpigs["output_frequency"] * 100),
        )

        # -------------- Status ---------------
        try:
            op_mode = OperatingMode(mode_raw)
        except ValueError:
            op_mode = OperatingMode.SUB  # default/unknown

        status = SystemStatus(
            operating_mode=op_mode,
            mode_name=mode_raw,
            inverter_time=None,
        )

        return battery, pv, grid, output, status

    # ==================================================== common builders ==
    def _create_battery_data(self, v: Dict[str, Any]) -> Optional[BatteryData]:
        try:
            return BatteryData(
                voltage=v["battery_voltage"],
                current=v["battery_current"],
                power=v["battery_power"],
                soc=v["battery_soc"],
                temperature=v["battery_temperature"],
            )
        except KeyError:
            return None

    def _create_pv_data(self, v: Dict[str, Any]) -> Optional[PVData]:
        if "pv_total_power" not in v and "pv1_voltage" not in v:
            return None
        return PVData(
            total_power=v.get("pv_total_power"),
            charging_power=v.get("pv_charging_power"),
            charging_current=v.get("pv_charging_current"),
            temperature=v.get("pv_temperature"),
            pv1_voltage=v.get("pv1_voltage"),
            pv1_current=v.get("pv1_current"),
            pv1_power=v.get("pv1_power"),
            pv2_voltage=v.get("pv2_voltage"),
            pv2_current=v.get("pv2_current"),
            pv2_power=v.get("pv2_power"),
            pv_generated_today=v.get("pv_energy_today"),
            pv_generated_total=v.get("pv_energy_total"),
        )

    def _create_grid_data(self, v: Dict[str, Any]) -> Optional[GridData]:
        if "grid_voltage" not in v:
            return None
        return GridData(
            voltage=v.get("grid_voltage"),
            power=v.get("grid_power"),
            frequency=v.get("grid_frequency"),
        )

    def _create_output_data(self, v: Dict[str, Any]) -> Optional[OutputData]:
        if "output_voltage" not in v:
            return None
        return OutputData(
            voltage=v.get("output_voltage"),
            current=v.get("output_current"),
            power=v.get("output_power"),
            apparent_power=v.get("output_apparent_power"),
            load_percentage=v.get("output_load_percentage"),
            frequency=v.get("output_frequency"),
        )

    def _create_system_status(self, v: Dict[str, Any]) -> Optional[SystemStatus]:
        if "operation_mode" not in v:
            return None
        try:
            op_mode = OperatingMode(v["operation_mode"])
        except ValueError:
            op_mode = OperatingMode.SUB
        ts = None
        if all(f"time_register_{i}" in v for i in range(6)):
            try:
                ts = datetime.datetime(
                    v["time_register_0"],
                    v["time_register_1"],
                    v["time_register_2"],
                    v["time_register_3"],
                    v["time_register_4"],
                    v["time_register_5"],
                )
            except (ValueError, TypeError):
                pass
        return SystemStatus(
            operating_mode=op_mode,
            mode_name=op_mode.name if isinstance(op_mode, OperatingMode) else str(op_mode),
            inverter_time=ts,
        )
