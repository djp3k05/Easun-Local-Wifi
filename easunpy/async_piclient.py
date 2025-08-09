import asyncio
import time
import logging
from .async_modbusclient import AsyncModbusClient   # we re‑use its UDP handshake

_LOGGER = logging.getLogger(__name__)

class AsyncPIClient(AsyncModbusClient):
    """
    Same handshake as AsyncModbusClient (UDP `set>server=…` + reverse‑TCP
    connection) but the payload is **plain ASCII terminated by CR (\\r)**,
    exactly what the Easun / MPP‑Solar “PI‑17” protocol expects.
    """

    async def send_bulk(self, commands: list[str], retry_count: int = 5) -> list[str]:
        async with self._lock:
            for attempt in range(retry_count):
                if not await self._ensure_connection():
                    await asyncio.sleep(1)
                    continue

                responses: list[str] = []
                try:
                    for cmd in commands:
                        if self._writer.is_closing():
                            self._connection_established = False
                            break

                        line = (cmd if cmd.endswith("\r") else f"{cmd}\r").encode()
                        _LOGGER.debug("Sending PI‑17 command: %s", cmd)
                        self._writer.write(line)
                        await self._writer.drain()

                        # PI‑17 replies always end with CR too
                        raw = await asyncio.wait_for(
                            self._reader.readuntil(b"\r"), timeout=5
                        )
                        txt = raw.decode(errors="ignore").strip()
                        _LOGGER.debug("Reply: %s", txt)
                        responses.append(txt)

                        self._last_activity = time.time()
                        await asyncio.sleep(0.05)          # tiny pacing gap

                    if len(responses) == len(commands):
                        return responses

                except (asyncio.IncompleteReadError, asyncio.TimeoutError) as err:
                    _LOGGER.warning("PI‑17 exchange failed: %s", err)
                    self._connection_established = False

            return []      # all retries failed
