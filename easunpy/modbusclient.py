# modbusclient.py
import socket
import struct
import time
import logging  # Import logging

from easunpy.crc import crc16_modbus, crc16_xmodem, adjust_crc_byte

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ModbusClient:
    def __init__(self, inverter_ip: str, local_ip: str, port: int = 8899):
        self.inverter_ip = inverter_ip
        self.local_ip = local_ip
        self.port = port
        self.request_id = 0  # Add request ID counter

    def send_udp_discovery(self) -> bool:
        """Perform UDP discovery to initialize the inverter communication."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
            udp_message = f"set>server={self.local_ip}:{self.port};"
            try:
                logger.debug(f"Sending UDP discovery message to {self.inverter_ip}:58899")
                udp_sock.sendto(udp_message.encode(), (self.inverter_ip, 58899))
                response, _ = udp_sock.recvfrom(1024)
                return True
            except socket.timeout:
                logger.error("UDP discovery timed out")
                return False
            except Exception as e:
                logger.error(f"Error sending UDP discovery message: {e}")
                return False

    def send(self, hex_command: str, retry_count: int = 2) -> str:
        """Send a Modbus TCP command."""
        command_bytes = bytes.fromhex(hex_command)
        logger.info(f"Sending command: {hex_command}")

        for attempt in range(retry_count):
            logger.debug(f"Attempt {attempt + 1} of {retry_count}")
            
            if not self.send_udp_discovery():
                logger.info("UDP discovery failed")
                time.sleep(1)
                continue

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_server:
                tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
                
                try:
                    # Attempt to bind to the local IP and port
                    logger.debug(f"Binding to {self.local_ip}:{self.port}")
                    tcp_server.bind((self.local_ip, self.port))
                    tcp_server.listen(1)

                    logger.debug("Waiting for client connection...")
                    client_sock, addr = tcp_server.accept()
                    logger.info(f"Client connected from {addr}")
                    
                    with client_sock:
                        logger.debug("Sending command bytes...")
                        client_sock.sendall(command_bytes)

                        logger.debug("Waiting for response...")
                        response = client_sock.recv(1024)
                        
                        if len(response) >= 6:
                            expected_length = int.from_bytes(response[4:6], 'big') + 6
                            
                            while len(response) < expected_length:
                                chunk = client_sock.recv(1024)
                                if not chunk:
                                    break
                                response += chunk

                        response_hex = response.hex()
                        logger.info(f"Received response: {response_hex}")
                        return response_hex

                except socket.timeout:
                    logger.info("Socket timeout")
                    time.sleep(1)
                    continue
                except Exception as e:
                    logger.error(f"Error: {str(e)}")
                    time.sleep(1)
                    continue

        logger.info("All retry attempts failed")
        return ""

def run_single_request(inverter_ip: str, local_ip: str, request: str):
    """
    Sends a single Modbus request to the inverter.
    """
    inverter = ModbusClient(inverter_ip=inverter_ip, local_ip=local_ip)
    response = inverter.send(request)
    return response

# Función para crear la solicitud completa
def create_request(transaction_id: int, protocol_id: int = 0x0001, ascii_command: Optional[str] = None,
                   unit_id: int = 0x01, function_code: int = 0x03,
                   register_address: int = 0, register_count: int = 1) -> str:
    """
    Create a Modbus command with the correct length and CRC for the RTU packet or ASCII command.
    """
    if ascii_command is not None:
        # ASCII mode
        rtu_packet = bytearray(ascii_command.encode('ascii'))
        crc = crc16_xmodem(rtu_packet)
        crc_high = adjust_crc_byte((crc >> 8) & 0xFF)
        crc_low = adjust_crc_byte(crc & 0xFF)
        rtu_packet.extend([crc_high, crc_low, 0x0D])
    else:
        # Numerical mode
        rtu_packet = bytearray([
            unit_id,
            function_code,
            (register_address >> 8) & 0xFF, register_address & 0xFF,
            (register_count >> 8) & 0xFF, register_count & 0xFF
        ])
        crc = crc16_modbus(rtu_packet)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        rtu_packet.extend([crc_low, crc_high])

    # Prefix with FF 04
    rtu_packet = bytearray([0xFF, 0x04]) + rtu_packet
    
    # Calculate total length
    length = len(rtu_packet)
    
    # Build full command
    command = bytearray([
        (transaction_id >> 8) & 0xFF, transaction_id & 0xFF,  # Transaction ID
        (protocol_id >> 8) & 0xFF, protocol_id & 0xFF,        # Protocol ID
        (length >> 8) & 0xFF, length & 0xFF                  # Longitud
    ]) + rtu_packet

    return command.hex()

def decode_modbus_response(response: str | bytes, register_count: int=1, data_format: str="Int", is_ascii: bool = False):
    """
    Decodes a Modbus TCP response using the provided format.
    :param response: Hexadecimal string or bytes of the Modbus response.
    :return: List of values for numerical, or string for ASCII.
    """
    if isinstance(response, str):
        response = bytes.fromhex(response)

    if len(response) < 9:
        return [] if not is_ascii else None

    # trans_id = response[0:2]
    # proto_id = response[2:4]
    len_bytes = response[4:6]
    msg_len = int.from_bytes(len_bytes, 'big')

    if len(response) < (6 + msg_len):
        return [] if not is_ascii else None

    payload = response[6:6+msg_len]

    if len(payload) < 3:
        return [] if not is_ascii else None

    # unit = payload[0]
    # func = payload[1]

    if is_ascii:
        data_bytes = payload[2:]
        if len(data_bytes) < 3:
            return None
        return data_bytes[:-3].decode('ascii')
    else:
        byte_count = payload[2]
        data_bytes = payload[3:]
        values = []
        for i in range(register_count):
            start = i * 2
            if start + 2 > len(data_bytes):
                break
            val_bytes = data_bytes[start:start+2]
            val = int.from_bytes(val_bytes, 'big')
            if data_format == "Int":
                if val & 0x8000:
                    val -= 0x10000
            values.append(val)
        return values

def get_registers_from_request(request: str) -> list:
    """
    Extracts register addresses from a Modbus request
    :param request: Hexadecimal string of the Modbus request
    :return: List of register addresses
    """
    rtu_payload = request[12:]  # Skip TCP header
    register_address = int(rtu_payload[8:12], 16)  # Get register address from RTU payload
    register_count = int(rtu_payload[12:16], 16)  # Get number of registers
    
    registers = []
    for i in range(register_count):
        registers.append(register_address + i)
        
    return registers
