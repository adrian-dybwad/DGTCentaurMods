"""
Millennium ChessLink BLE Protocol Client

Provides protocol-specific handling for Millennium chess boards using BLE.
Uses the generic BLEClient or GatttoolClient for low-level BLE operations.
"""

from typing import Callable

from DGTCentaurMods.board.logging import log


# Millennium ChessLink BLE UUIDs
# The service UUID is the full 128-bit UUID, but the characteristics use
# short 16-bit UUIDs (fff1, fff2) in the standard Bluetooth base UUID format
MILLENNIUM_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
MILLENNIUM_RX_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # Write commands TO device
MILLENNIUM_TX_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # Notify responses FROM device


def odd_parity(b: int) -> int:
    """Calculate odd parity for a byte and set MSB if needed.
    
    Args:
        b: Byte value (0-127)
    
    Returns:
        Byte with odd parity (MSB set if needed)
    """
    byte = b & 127
    par = 1
    for _ in range(7):
        bit = byte & 1
        byte = byte >> 1
        par = par ^ bit
    if par == 1:
        byte = b | 128
    else:
        byte = b & 127
    return byte


def decode_odd_parity(byte_with_parity: int) -> int:
    """Decode a byte with odd parity (strip MSB).
    
    Args:
        byte_with_parity: Byte with parity bit in MSB
        
    Returns:
        Decoded byte (7 bits)
    """
    return byte_with_parity & 0x7F


def encode_command(command_text: str) -> bytes:
    """Encode a Millennium protocol command with odd parity and XOR CRC.
    
    Uses the old Millennium protocol format with odd parity encoding.
    
    Args:
        command_text: The command string to encode (e.g., "S")
    
    Returns:
        Encoded command with odd parity and CRC appended
    """
    # Calculate CRC (XOR of all ASCII characters)
    cs = 0
    for char in command_text:
        cs = cs ^ ord(char)
    
    # Convert CRC to hex string
    h = f"0x{cs:02x}"
    h1 = h[2:3]  # First hex digit
    h2 = h[3:4]  # Second hex digit
    
    # Build encoded packet with odd parity
    tosend = bytearray()
    # Encode each character in command with odd parity
    for char in command_text:
        tosend.append(odd_parity(ord(char)))
    # Encode CRC hex digits with odd parity
    tosend.append(odd_parity(ord(h1)))
    tosend.append(odd_parity(ord(h2)))
    
    return bytes(tosend)


def decode_response(data: bytes) -> str:
    """Decode a Millennium protocol response by stripping odd parity.
    
    Args:
        data: Raw bytes from the device
        
    Returns:
        Decoded ASCII string
    """
    decoded = bytearray()
    for b in data:
        decoded.append(decode_odd_parity(b))
    return decoded.decode('ascii', errors='replace')


class MillenniumClient:
    """Protocol handler for Millennium ChessLink boards.
    
    Handles Millennium-specific protocol encoding/decoding and provides
    methods for common operations like probing and sending commands.
    """
    
    def __init__(self, on_response: Callable[[str], None] | None = None):
        """Initialize the Millennium client.
        
        Args:
            on_response: Optional callback for decoded responses
        """
        self.on_response = on_response
        self.response_buffer: bytearray = bytearray()
        self._got_response = False
        self.rx_char_uuid: str | None = None  # Write TO device
        self.tx_char_uuid: str | None = None  # Notify FROM device
    
    @property
    def service_uuid(self) -> str:
        """Return the Millennium service UUID."""
        return MILLENNIUM_SERVICE_UUID
    
    @property
    def rx_uuid(self) -> str:
        """Return the RX characteristic UUID (write to device)."""
        return MILLENNIUM_RX_CHAR_UUID
    
    @property
    def tx_uuid(self) -> str:
        """Return the TX characteristic UUID (notify from device)."""
        return MILLENNIUM_TX_CHAR_UUID
    
    def notification_handler(self, sender, data: bytearray):
        """Handle notifications from Millennium TX characteristic.
        
        Accumulates data until a complete response is received, then
        decodes and logs it.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Millennium] ({len(data)} bytes): {hex_str}")
        
        # Skip echo-backs (single byte with 0x01 prefix)
        if len(data) == 2 and data[0] == 0x01:
            log.debug(f"Ignoring echo-back: {hex_str}")
            return
        
        # Strip 0x01 prefix if present
        if len(data) > 0 and data[0] == 0x01:
            data = data[1:]
        
        if len(data) == 0:
            return
        
        # Accumulate response
        self.response_buffer.extend(data)
        
        # Decode odd parity
        decoded = bytearray()
        for b in self.response_buffer:
            decoded.append(decode_odd_parity(b))
                        
        # Check for complete response
        if len(decoded) >= 3:
            first_char = chr(decoded[0]) if decoded[0] < 128 else '?'
            
            # Check for complete responses based on command type
            complete = False
            if first_char == 'x' and len(decoded) >= 3:
                complete = True
            elif first_char == 'w' and len(decoded) >= 7:
                complete = True
            elif first_char == 's' and len(decoded) >= 67:
                complete = True
            
            if complete:
                ascii_str = decoded.decode('ascii', errors='replace')
                log.info(f"RX [Millennium DECODED]: {ascii_str}")
                self.response_buffer.clear()
                self._got_response = True
                
                if self.on_response:
                    self.on_response(ascii_str)
    
    def gatttool_notification_handler(self, handle: int, data: bytearray):
        """Handle notifications when using gatttool backend.
        
        Args:
            handle: The characteristic handle
            data: The notification data
        """
        log.info(f"RX [Millennium] ({len(data)} bytes): {data.hex()}")
        decoded = bytearray(decode_odd_parity(b) for b in data)
        try:
            ascii_str = decoded.decode('ascii', errors='replace')
            log.info(f"RX [Millennium DECODED]: {ascii_str}")
            self._got_response = True
            if self.on_response:
                self.on_response(ascii_str)
        except Exception:
            pass
    
    def encode_command(self, command: str) -> bytes:
        """Encode a command for the Millennium protocol.
        
        Args:
            command: Command string (e.g., "S", "W0203", "X")
            
        Returns:
            Encoded bytes ready to send
        """
        return encode_command(command)
    
    def got_response(self) -> bool:
        """Check if a response was received since last reset.
        
        Returns:
            True if a response was received
        """
        return self._got_response
    
    def reset_response_flag(self):
        """Reset the response flag for the next probe."""
        self._got_response = False
        self.response_buffer.clear()
    
    def get_initialization_commands(self) -> list[str]:
        """Return the sequence of commands to initialize the board.
        
        Returns:
            List of command strings
        """
        return ["W0203", "W0407", "X", "S"]
    
    def get_probe_command(self) -> str:
        """Return the command used to probe for this protocol.
        
        Returns:
            The probe command string
        """
        return "S"
    
    def get_status_command(self) -> str:
        """Return the command used to request board status.
        
        Returns:
            The status command string
        """
        return "S"
    
    async def probe_with_bleak(self, ble_client) -> bool:
        """Probe for Millennium protocol using bleak BLEClient.
        
        Args:
            ble_client: BLEClient instance
            
        Returns:
            True if protocol detected and initialized, False otherwise
        """
        import asyncio
        
        # Helper to find characteristic UUID
        def find_char_uuid(target_uuid: str) -> str | None:
            if not ble_client.services:
                return None
            target_lower = target_uuid.lower()
            for service in ble_client.services:
                for char in service.characteristics:
                    if char.uuid.lower() == target_lower:
                        return char.uuid
            return None
        
        rx_uuid = find_char_uuid(self.rx_uuid)
        tx_uuid = find_char_uuid(self.tx_uuid)
        
        if not rx_uuid or not tx_uuid:
            log.info("Millennium characteristics not found")
            return False
        
        log.info(f"Found Millennium RX: {rx_uuid}")
        log.info(f"Found Millennium TX: {tx_uuid}")
        
        # Store UUIDs for later use
        self._bleak_rx_uuid = rx_uuid
        self._bleak_tx_uuid = tx_uuid
        self._ble_client = ble_client
        
        # Enable notifications on TX
        if not await ble_client.start_notify(tx_uuid, self.notification_handler):
            log.warning("Failed to enable Millennium notifications")
            return False
        
        # Send probe command
        self.reset_response_flag()
        s_cmd = self.encode_command(self.get_probe_command())
        log.info(f"Sending Millennium S probe: {' '.join(f'{b:02x}' for b in s_cmd)}")
        
        if not await ble_client.write_characteristic(rx_uuid, s_cmd, response=False):
            log.warning("Failed to send Millennium probe")
            return False
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self.got_response():
                break
        
        # Send initialization sequence
        for cmd in self.get_initialization_commands():
            encoded = self.encode_command(cmd)
            log.info(f"Sending Millennium '{cmd}': {' '.join(f'{b:02x}' for b in encoded)}")
            await ble_client.write_characteristic(rx_uuid, encoded, response=False)
            await asyncio.sleep(0.5)
        
        log.info("Millennium protocol active")
        return True
    
    async def send_periodic_commands_bleak(self, ble_client) -> None:
        """Send periodic commands using bleak BLEClient.
        
        Args:
            ble_client: BLEClient instance
        """
        if hasattr(self, '_bleak_rx_uuid') and self._bleak_rx_uuid:
            s_cmd = self.encode_command(self.get_status_command())
            log.info("Sending periodic Millennium S command")
            await ble_client.write_characteristic(self._bleak_rx_uuid, s_cmd, response=False)
    
    async def probe_with_gatttool(self, gatttool_client) -> bool:
        """Probe for Millennium protocol using gatttool client.
        
        Args:
            gatttool_client: GatttoolClient instance
            
        Returns:
            True if protocol detected and initialized, False otherwise
        """
        import asyncio
        
        rx_char = gatttool_client.find_characteristic_by_uuid(self.rx_uuid)
        tx_char = gatttool_client.find_characteristic_by_uuid(self.tx_uuid)
        
        if not rx_char or not tx_char:
            log.info("Millennium characteristics not found")
            return False
        
        log.info(f"Found Millennium RX: handle {rx_char['value_handle']:04x}")
        log.info(f"Found Millennium TX: handle {tx_char['value_handle']:04x}")
        
        # Store handles for later use
        self._rx_handle = rx_char['value_handle']
        self._tx_handle = tx_char['value_handle']
        
        # Enable notifications on TX
        await gatttool_client.enable_notifications(
            tx_char['value_handle'], self.gatttool_notification_handler
        )
        
        # Send probe command
        self.reset_response_flag()
        s_cmd = self.encode_command(self.get_probe_command())
        log.info(f"Sending Millennium S probe: {s_cmd.hex()}")
        await gatttool_client.write_characteristic(
            rx_char['value_handle'], s_cmd, response=False
        )
        
        await asyncio.sleep(2)
        
        log.info("Millennium protocol active")
        return True
    
    async def send_periodic_commands(self, gatttool_client) -> None:
        """Send periodic commands using gatttool client.
        
        Args:
            gatttool_client: GatttoolClient instance
        """
        if hasattr(self, '_rx_handle') and self._rx_handle:
            s_cmd = self.encode_command(self.get_status_command())
            log.info("Sending periodic Millennium S command")
            await gatttool_client.write_characteristic(
                self._rx_handle, s_cmd, response=False
            )
    
    def get_write_handle(self) -> int | None:
        """Return the write handle for gatttool operations."""
        return getattr(self, '_rx_handle', None)
    
    def get_read_handle(self) -> int | None:
        """Return the read/notify handle for gatttool operations."""
        return getattr(self, '_tx_handle', None)

