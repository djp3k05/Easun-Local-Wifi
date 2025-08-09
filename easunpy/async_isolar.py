"""
async_isolar.py – unified driver for Easun / ISolar / Voltronic inverters

Supports two wire‑protocols that share the same Home‑Assistant / CLI
interface:

* Modbus‑TCP (default for SMG‑II and most rebadged models)
* PI‑17 ASCII (“QPIGS”, “QPIRI”, …) used by Easun SMW 8 kW / 11 kW

The right transport is picked at runtime from MODEL_CONFIGS[…].protocol.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Dict, List, Optional, Tuple, Any

from .async_modbusclient import AsyncModbusClient
from .async_piclient     import AsyncPIClient               # <- new
from .modbusclient       import create_request, decode_modbus_response
from .pi_parsers         import (                           # <- new
    parse_qpigs,
    parse_qmod,
    parse_qbeqi,
    parse_qpiri,
)

from .isolar import (
    BatteryData,
    PVData,
    GridData,
    OutputData,
    SystemStatus,
    OperatingMode,
)
from .models import MODEL_CONFIGS, ModelConfig

_LOGGER = logging.getLogger(__name__)


class AsyncISolar:
    """High‑level asynchronous wrapper that delivers *parsed* data tuples."""

    # --------------------------------------------------------------------- #
    # construction / configuration
    # --------------------------------------------------------------------- #

    def __init__(
        self,
        inverter_ip: str,
        local_ip: str,
        model: str = "ISOLAR_SMG_II_11K",
    ):
        if model not in MODEL_CONFIGS:
            raise ValueError(
                f"Unknown inverter model '{model}'. "
                f"Supported: {list(MODEL_CONFIGS)}"
            )

        self.model: str = model
        self.model_config: ModelConfig = MODEL_CONFIGS[model]

        # choose the correct transport
        if self.model_config.protocol == "pi17":
            self.client: AsyncModbusClient | AsyncPIClient = AsyncPIClient(
                inverter_ip=inverter_ip, local_ip=local_ip
            )
        else:  # default: Modbus
            self.client = AsyncModbusClient(
                inverter_ip=inverter_ip, local_ip=local_ip
            )

        self._transaction_id: int = 0x0772
        _LOGGER.info(
            "AsyncISolar initialised – model=%s, protocol=%s",
            self.model,
            self.model_config.protocol,
        )

    def update_model(self, model: str) -> None:
        """Hot‑swap the model (and therefore protocol + register map)."""
        if model not in MODEL_CONFIGS:
            raise ValueError(f"Unknown inverter model '{model}'")

        self.model = model
        self.model_config = MODEL_CONFIGS[model]

        # Re‑create transport if protocol changed
        proto = self.model_config.protocol
        if proto == "pi17" and not isinstance(self.client, AsyncPIClient):
            self.client = AsyncPIClient(
                inverter_ip=self.client.inverter_ip,
                local_ip=self.client.local_ip,
            )
        elif proto == "modbus" and not isinstance(
            self.client, AsyncModbusClient
        ):
            self.client = AsyncModbusClient(
                inverter_ip=self.client.inverter_ip,
                local_ip=self.client.local_ip,
            )

        _LOGGER.info("AsyncISolar switched to model=%s (protocol=%s)", model, proto)

    # --------------------------------------------------------------------- #
    # public API
    # --------------------------------------------------------------------- #

    async def get_all_data(
        self,
    ) -> Tuple[
        Optional[BatteryData],
        Optional[PVData],
        Optional[GridData],
        Optional[OutputData],
        Optional[SystemStatus],
    ]:
        """
        Return a *single* coherent snapshot of inverter metrics.

        The tuple layout is constant across protocols.
        """
        if self.model_config.protocol == "pi17":
            return await self._get_all_data_pi17()
        return await self._get_all_data_modbus()

    # --------------------------------------------------------------------- #
    # ------------------------  PI‑17   implementation  ------------------- #
    # --------------------------------------------------------------------- #

    async def _get_all_data_pi17(
        self,
    ) -> Tuple[
        Optional[BatteryData],
        Optional[PVData],
        Optional[GridData],
        Optional[OutputData],
        Optional[SystemStatus],
    ]:
        """
        Poll the four mandatory PI‑17 commands and build the data classes.

        Commands issued (one TCP session):
          QPIGS – instantaneous measurements
          QMOD  – operating mode
          QBEQI – battery equalisation (gives SoC etc.)
          QPIRI – rating info (some fields reused for sensors)

        Only the fields actually surfaced as HA entities are parsed.
        """

        cmds: List[str] = ["QPIGS", "QMOD", "QBEQI", "QPIRI"]
        replies: List[str] = await self.client.send_bulk(cmds)

        if len(replies) != 4:
            _LOGGER.error("PI‑17: missing replies – got %s", replies)
            return (None, None, None, None, None)

        # --- first level parsing -------------------------------------------------
        try:
            r_qpigs = parse_qpigs(replies[0])
            mode_raw = parse_qmod(replies[1])
            r_qbeqi = parse_qbeqi(replies[2])
            # r_qbeqi currently only used for SoC – keep for extensions
            r_qpiri = parse_qpiri(replies[3])
        except Exception as exc:
            _LOGGER.error("PI‑17 parse error: %s", exc)
            return (None, None, None, None, None)

        # --- build dataclasses ---------------------------------------------------
        battery = BatteryData(
            voltage=r_qpigs["battery_voltage"],
            current=r_qpigs["battery_chg_current"],
            power=int(
                r_qpigs["battery_chg_current"] * r_qpigs["battery_voltage"]
            ),
            soc=r_qpigs["battery_soc"],
            temperature=r_qpigs["inverter_temp"],
        )

        pv = PVData(
            total_power=r_qpigs["pv_power"],
            charging_power=r_qpigs["pv_power"],
            charging_current=r_qpigs["pv_current"],
            temperature=r_qpigs["inverter_temp"],
            pv1_voltage=r_qpigs["pv_voltage"],
            pv1_current=r_qpigs["pv_current"],
            pv1_power=r_qpigs["pv_power"],
            pv2_voltage=0.0,
            pv2_current=0,
            pv2_power=0,
            pv_generated_today=0,
            pv_generated_total=0,
        )

        grid = GridData(
            voltage=r_qpigs["grid_voltage"],
            power=r_qpigs["output_active_pow"],  # imported (+) / exported (‑)
            frequency=int(r_qpigs["grid_frequency"] * 100),  # centi‑Hz
        )

        output = OutputData(
            voltage=r_qpigs["output_voltage"],
            current=0.0,
            power=r_qpigs["output_active_pow"],
            apparent_power=r_qpigs["output_apparent_pow"],
            load_percentage=r_qpigs["load_percent"],
            frequency=int(r_qpigs["output_frequency"] * 100),
        )

        op_mode = (
            OperatingMode(mode_raw)
            if mode_raw in OperatingMode._value2member_map_
            else OperatingMode.SUB
        )

        status = SystemStatus(
            operating_mode=op_mode,
            mode_name=mode_raw,
            inverter_time=None,
        )

        return battery, pv, grid, output, status

    # --------------------------------------------------------------------- #
    # ------------------------  Modbus implementation  -------------------- #
    # --------------------------------------------------------------------- #

    # (all code below is lifted from the original async_isolar.py with only
    #  trivial renames; no functional changes)

    def _get_next_transaction_id(self) -> int:
        current_id = self._transaction_id
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return current_id

    async def _get_all_data_modbus(
        self,
    ) -> Tuple[
        Optional[BatteryData],
        Optional[PVData],
        Optional[GridData],
        Optional[OutputData],
        Optional[SystemStatus],
    ]:
        """Original Modbus bulk‑read path."""

        register_groups = self._create_register_groups()
        if not register_groups:  # model without register map (e.g. SMW)
            _LOGGER.warning("Model %s has no Modbus register map", self.model)
            return (None, None, None, None, None)

        raw_groups = await self._read_registers_bulk(register_groups)
        if not raw_groups:
            return (None, None, None, None, None)

        # map raw words → logical names → scaled values
        values: Dict[str, Any] = {}
        for grp_idx, (start, count) in enumerate(register_groups):
            data = raw_groups[grp_idx]
            if data is None:
                continue

            for reg_name, cfg in self.model_config.register_map.items():
                if start <= cfg.address < start + count:
                    idx = cfg.address - start
                    if idx < len(data):
                        values[reg_name] = self.model_config.process_value(
                            reg_name, data[idx]
                        )

        return (
            self._create_battery_data(values),
            self._create_pv_data(values),
            self._create_grid_data(values),
            self._create_output_data(values),
            self._create_system_status(values),
        )

    # ------------------------------------------------------------------ #
    # ------------ helper methods (unchanged from original) -------------#
    # ------------------------------------------------------------------ #

    async def _read_registers_bulk(
        self,
        register_groups: List[Tuple[int, int]],
        data_format: str = "Int",
    ) -> List[Optional[List[int]]]:
        """Send several Modbus requests in one TCP session."""
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
            _LOGGER.debug("Modbus bulk read: %s", register_groups)
            responses = await self.client.send_bulk(requests)

            out: List[Optional[List[int]]] = [None] * len(register_groups)
            for i, (resp, (_, cnt)) in enumerate(zip(responses, register_groups)):
                if not resp:
                    _LOGGER.warning("Empty response for group %s", register_groups[i])
                    continue
                try:
                    out[i] = decode_modbus_response(resp, cnt, data_format)
                except Exception as exc:  # pragma: no cover
                    _LOGGER.warning("Decode failed for group %s: %s", register_groups[i], exc)
            return out
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("Bulk read failed: %s", exc)
            return [None] * len(register_groups)

    # ------------ register grouping & dataclass construction ------------ #

    def _create_register_groups(self) -> List[Tuple[int, int]]:
        addresses = sorted(
            cfg.address
            for cfg in self.model_config.register_map.values()
            if cfg.address > 0
        )
        if not addresses:
            return []
        groups: List[Tuple[int, int]] = []
        start = end = addresses[0]
        for addr in addresses[1:]:
            if addr <= end + 10:  # allow small holes
                end = addr
            else:
                groups.append((start, end - start + 1))
                start = end = addr
        groups.append((start, end - start + 1))
        return groups

    # the _create_* helpers are unchanged from the original file --------- #

    def _create_battery_data(self, v: Dict[str, Any]) -> Optional[BatteryData]:
        try:
            if all(k in v for k in ("battery_voltage", "battery_current", "battery_power", "battery_soc", "battery_temperature")):
                return BatteryData(
                    voltage=v["battery_voltage"],
                    current=v["battery_current"],
                    power=v["battery_power"],
                    soc=v["battery_soc"],
                    temperature=v["battery_temperature"],
                )
        except Exception as exc:
            _LOGGER.debug("BatteryData build failed: %s", exc)
        return None

    def _create_pv_data(self, v: Dict[str, Any]) -> Optional[PVData]:
        try:
            if any(k in v for k in ("pv_total_power", "pv1_voltage", "pv2_voltage")):
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
        except Exception as exc:
            _LOGGER.debug("PVData build failed: %s", exc)
        return None

    def _create_grid_data(self, v: Dict[str, Any]) -> Optional[GridData]:
        try:
            if any(k in v for k in ("grid_voltage", "grid_power", "grid_frequency")):
                return GridData(
                    voltage=v.get("grid_voltage"),
                    power=v.get("grid_power"),
                    frequency=v.get("grid_frequency"),
                )
        except Exception as exc:
            _LOGGER.debug("GridData build failed: %s", exc)
        return None

    def _create_output_data(self, v: Dict[str, Any]) -> Optional[OutputData]:
        try:
            if any(k in v for k in ("output_voltage", "output_power")):
                return OutputData(
                    voltage=v.get("output_voltage"),
                    current=v.get("output_current"),
                    power=v.get("output_power"),
                    apparent_power=v.get("output_apparent_power"),
                    load_percentage=v.get("output_load_percentage"),
                    frequency=v.get("output_frequency"),
                )
        except Exception as exc:
            _LOGGER.debug("OutputData build failed: %s", exc)
        return None

    def _create_system_status(self, v: Dict[str, Any]) -> Optional[SystemStatus]:
        inverter_time = None
        try:
            if all(f"time_register_{i}" in v for i in range(6)):
                inverter_time = _dt.datetime(
                    v["time_register_0"],
                    v["time_register_1"],
                    v["time_register_2"],
                    v["time_register_3"],
                    v["time_register_4"],
                    v["time_register_5"],
                )
        except Exception as exc:  # pragma: no cover
            _LOGGER.debug("Timestamp build failed: %s", exc)

        if "operation_mode" in v:
            try:
                op_mode = OperatingMode(v["operation_mode"])
            except ValueError:
                op_mode = OperatingMode.SUB

            return SystemStatus(
                operating_mode=op_mode,
                mode_name=op_mode.name if isinstance(op_mode, OperatingMode) else str(op_mode),
                inverter_time=inverter_time,
            )
        return None
