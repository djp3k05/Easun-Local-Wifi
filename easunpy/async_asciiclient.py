# easunpy/async_asciiclient.py
# Asynchronous client for Voltronic ASCII-based inverters.

import asyncio
import logging
import socket
import time
from typing import List, Optional

from .crc_xmodem import crc16_xmodem, adjust_crc_byte

logger = logging.getLogger(__name__)

class AsyncAsciiClient:
    """
    Handles the async communication with an ASCII-based inverter.
    """
    def __init__(self, inverter_ip: str, local_ip: str, port: int = 502):
        self.inverter_ip = inverter_ip
        self.local_ip = local_ip
        self.port = port
        self._lock = asyncio.Lock()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._server: Optional[asyncio.AbstractServer] = None
        self._connection_established = asyncio.Event()
        self._transaction_id = 0x15a8  # Starting transaction ID from PowerShell script

    async def _get_next_transaction_id(self) -> int:
        """Get the next transaction ID."""
        current_id = self._transaction_id
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return current_id

    def _build_command_packet(self, command: str) -> bytes:
        """Builds the command packet with wrapper and CRC."""
        trans_id = self._get_next_transaction_id()
        command_bytes = command.encode('ascii')
        
        crc = crc16_xmodem(command_bytes)
        crc_high = adjust_crc_byte((crc >> 8) & 0xFF)
        crc_low = adjust_crc_byte(crc & 0xFF)
        
        data = command_bytes + bytes([crc_high, crc_low, 0x0D])
        
        length = len(data) + 2  # + unit (ff) + func (04)
        
        packet = bytearray([
            (trans_id >> 8) & 0xFF,
            trans_id & 0xFF,
            0x00, 0x01,  # Protocol ID
            (length >> 8) & 0xFF,
            length & 0xFF,
            0xFF,  # Unit ID
            0x04   # Function Code
        ]) + data
        
        return bytes(packet)

    async def _handle_connection(self, reader, writer):
        """Callback to handle a new client connection."""
        if self._connection_established.is_set():
            logger.warning("Another connection attempted while one is active. Closing new one.")
            writer.close()
            await writer.wait_closed()
            return
            
        logger.info(f"Inverter connected from {writer.get_extra_info('peername')}")
        self._reader = reader
        self._writer = writer
        self._connection_established.set()

    async def connect(self):
        """Initiates discovery and waits for the inverter to connect back."""
        async with self._lock:
            if self._connection_established.is_set():
                return

            # Start listening for the inverter's connection
            self._server = await asyncio.start_server(
                self._handle_connection, self.local_ip, self.port
            )
            logger.info(f"Listening on {self.local_ip}:{self.port} for inverter connection...")

            # Send UDP discovery to trigger the inverter
            udp_message = f"set>server={self.local_ip}:{self.port};".encode('ascii')
            loop = asyncio.get_event_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=(self.inverter_ip, 58899)
            )
            transport.sendto(udp_message)
            transport.close()
            logger.info(f"Sent discovery packet to {self.inverter_ip}:58899")

            # Wait for the inverter to connect
            try:
                await asyncio.wait_for(self._connection_established.wait(), timeout=15)
            except asyncio.TimeoutError:
                await self.disconnect()
                raise ConnectionError("Timeout waiting for inverter to connect back.")

    async def disconnect(self):
        """Disconnects and cleans up resources."""
        async with self._lock:
            if self._writer:
                self._writer.close()
                await self._writer.wait_closed()
            if self._server:
                self._server.close()
                await self._server.wait_closed()
            
            self._reader = None
            self._writer = None
            self._server = None
            self._connection_established.clear()
            logger.info("Disconnected from inverter.")

    async def send_command(self, command: str) -> str:
        """Sends a command and returns the parsed ASCII response."""
        async with self._lock:
            if not self._connection_established.is_set() or not self._writer or not self._reader:
                await self.connect()

            if not self._writer or not self._reader:
                 raise ConnectionError("Connection not established.")

            packet = self._build_command_packet(command)
            logger.debug(f"Sending command '{command}': {packet.hex()}")
            self._writer.write(packet)
            await self._writer.drain()

            # Read response header
            header = await self._reader.readexactly(6)
            length = int.from_bytes(header[4:6], 'big')
            
            # Read the rest of the response
            response_data = await self._reader.readexactly(length)
            
            # The full response includes the wrapper
            full_response = header + response_data
            logger.debug(f"Received response: {full_response.hex()}")

            # Parse out the ASCII data
            # Data starts after Unit ID and Func Code (2 bytes), ends before CRC (2 bytes) and \r (1 byte)
            raw_data_bytes = response_data[2:-3]
            parsed_response = raw_data_bytes.decode('ascii')
            logger.debug(f"Parsed response for '{command}': {parsed_response}")
            
            return parsed_response
