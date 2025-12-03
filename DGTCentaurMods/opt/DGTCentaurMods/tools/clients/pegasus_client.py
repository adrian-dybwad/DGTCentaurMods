"""
DGT Pegasus BLE Protocol Client

Provides protocol-specific handling for DGT Pegasus chess boards using BLE.
Uses the Nordic UART Service (NUS) for communication.
Uses the generic BLEClient or GatttoolClient for low-level BLE operations.
"""

from typing import Callable

from DGTCentaurMods.board.logging import log


# DGT Pegasus BLE UUIDs (Nordic UART Service - NUS)
PEGASUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
PEGASUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Write commands TO device
PEGASUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # Notify responses FROM device

# DGT Protocol Commands (similar to serial protocol)
DGT_SEND_RESET = 0x40
DGT_SEND_BRD = 0x42
DGT_SEND_UPDATE = 0x43
DGT_SEND_UPDATE_BRD = 0x44
DGT_RETURN_SERIALNR = 0x45
DGT_RETURN_BUSADRES = 0x46
DGT_SEND_TRADEMARK = 0x47
DGT_SEND_VERSION = 0x4D
DGT_SEND_UPDATE_NICE = 0x4B
DGT_SEND_EE_MOVES = 0x49
DGT_SEND_BATTERY_STATUS = 0x4C


class PegasusClient:
    """Protocol handler for DGT Pegasus boards.
    
    Handles Pegasus-specific protocol (DGT serial protocol over BLE NUS)
    and provides methods for common operations like probing and sending commands.
    """
    
    def __init__(
        self,
        on_board: Callable[[bytes], None] | None = None,
        on_data: Callable[[bytes], None] | None = None
    ):
        """Initialize the Pegasus client.
        
        Args:
            on_board: Optional callback for board state updates
            on_data: Optional callback for raw data
        """
        self.on_board = on_board
        self.on_data = on_data
        self._got_response = False
        self.rx_char_uuid: str | None = None  # Write TO device
        self.tx_char_uuid: str | None = None  # Notify FROM device
    
    @property
    def service_uuid(self) -> str:
        """Return the NUS service UUID."""
        return PEGASUS_SERVICE_UUID
    
    @property
    def rx_uuid(self) -> str:
        """Return the RX characteristic UUID (write to device)."""
        return PEGASUS_RX_CHAR_UUID
    
    @property
    def tx_uuid(self) -> str:
        """Return the TX characteristic UUID (notify from device)."""
        return PEGASUS_TX_CHAR_UUID
    
    def notification_handler(self, sender, data: bytearray):
        """Handle notifications from Pegasus TX characteristic.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        self._got_response = True
        log.info(f"RX [Pegasus] ({len(data)} bytes): {data.hex()}")
        
        if self.on_data:
            self.on_data(bytes(data))
        
        # Try to decode as ASCII if printable
        try:
            ascii_str = data.decode('ascii', errors='replace')
            printable = ''.join(c if c.isprintable() or c in '\r\n' else '.' for c in ascii_str)
            log.info(f"RX [Pegasus ASCII]: {printable}")
        except Exception:
            pass
        
        # Check for board state response (starts with message ID)
        if len(data) > 0:
            msg_id = data[0]
            if msg_id == 0x06 and len(data) >= 67:
                # Board dump response (0x06 + 64 squares + 2 byte checksum)
                log.info("Received board state")
                if self.on_board:
                    self.on_board(bytes(data))
    
    def gatttool_notification_handler(self, handle: int, data: bytearray):
        """Handle notifications when using gatttool backend.
        
        Args:
            handle: The characteristic handle
            data: The notification data
        """
        log.info(f"RX [Pegasus] ({len(data)} bytes): {data.hex()}")
        self._got_response = True
        
        if self.on_data:
            self.on_data(bytes(data))
        
        # Try to decode as ASCII if printable
        try:
            ascii_str = data.decode('ascii', errors='replace')
            printable = ''.join(c if c.isprintable() or c in '\r\n' else '.' for c in ascii_str)
            log.info(f"RX [Pegasus ASCII]: {printable}")
        except Exception:
            pass
    
    def get_reset_command(self) -> bytes:
        """Return the reset command.
        
        Returns:
            Command bytes
        """
        return bytes([DGT_SEND_RESET])
    
    def get_board_command(self) -> bytes:
        """Return the command to request board state.
        
        Returns:
            Command bytes
        """
        return bytes([DGT_SEND_BRD])
    
    def get_version_command(self) -> bytes:
        """Return the command to request firmware version.
        
        Returns:
            Command bytes
        """
        return bytes([DGT_SEND_VERSION])
    
    def get_battery_command(self) -> bytes:
        """Return the command to request battery status.
        
        Returns:
            Command bytes
        """
        return bytes([DGT_SEND_BATTERY_STATUS])
    
    def get_update_command(self) -> bytes:
        """Return the command to enable update mode.
        
        Returns:
            Command bytes
        """
        return bytes([DGT_SEND_UPDATE_NICE])
    
    def got_response(self) -> bool:
        """Check if a response was received since last reset.
        
        Returns:
            True if a response was received
        """
        return self._got_response
    
    def reset_response_flag(self):
        """Reset the response flag for the next probe."""
        self._got_response = False
    
    def get_probe_commands(self) -> list[bytes]:
        """Return the sequence of commands to probe for this protocol.
        
        Returns:
            List of command bytes
        """
        return [
            self.get_reset_command(),
            self.get_board_command()
        ]
    
    async def probe_with_bleak(self, ble_client) -> bool:
        """Probe for DGT Pegasus protocol using bleak BLEClient.
        
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
        
        tx_uuid = find_char_uuid(self.tx_uuid)
        rx_uuid = find_char_uuid(self.rx_uuid)
        
        if not tx_uuid or not rx_uuid:
            log.info("Pegasus characteristics not found")
            return False
        
        log.info(f"Found Pegasus TX (notify): {tx_uuid}")
        log.info(f"Found Pegasus RX (write): {rx_uuid}")
        
        # Store UUIDs for later use
        self._bleak_tx_uuid = tx_uuid
        self._bleak_rx_uuid = rx_uuid
        self._ble_client = ble_client
        
        # Enable notifications on TX characteristic
        await ble_client.start_notify(tx_uuid, self.notification_handler)
        
        # Send probe commands
        self.reset_response_flag()
        for probe_cmd in self.get_probe_commands():
            log.info(f"Sending Pegasus probe: {probe_cmd.hex()}")
            if not await ble_client.write_characteristic(rx_uuid, probe_cmd, response=False):
                log.warning("Failed to send Pegasus probe")
                return False
            await asyncio.sleep(0.5)
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self.got_response():
                break
        
        # Even if no response, if we found the characteristics, consider it detected
        log.info("DGT Pegasus protocol active")
        return True
    
    async def send_periodic_commands_bleak(self, ble_client) -> None:
        """Send periodic commands using bleak BLEClient.
        
        Args:
            ble_client: BLEClient instance
        """
        if hasattr(self, '_bleak_rx_uuid') and self._bleak_rx_uuid:
            cmd = self.get_board_command()
            log.info("Sending periodic Pegasus board request")
            await ble_client.write_characteristic(self._bleak_rx_uuid, cmd, response=False)
    
    async def probe_with_gatttool(self, gatttool_client) -> bool:
        """Probe for DGT Pegasus protocol using gatttool client.
        
        Args:
            gatttool_client: GatttoolClient instance
            
        Returns:
            True if protocol detected and initialized, False otherwise
        """
        import asyncio
        
        rx_char = gatttool_client.find_characteristic_by_uuid(self.rx_uuid)
        tx_char = gatttool_client.find_characteristic_by_uuid(self.tx_uuid)
        
        if not rx_char or not tx_char:
            log.info("Pegasus characteristics not found")
            return False
        
        log.info(f"Found Pegasus RX (write): handle {rx_char['value_handle']:04x}")
        log.info(f"Found Pegasus TX (notify): handle {tx_char['value_handle']:04x}")
        
        # Store handles for later use
        self._rx_handle = rx_char['value_handle']
        self._tx_handle = tx_char['value_handle']
        
        # Enable notifications on TX characteristic
        await gatttool_client.enable_notifications(
            tx_char['value_handle'], self.gatttool_notification_handler
        )
        
        # Send probe commands
        self.reset_response_flag()
        for probe_cmd in self.get_probe_commands():
            log.info(f"Sending Pegasus probe: {probe_cmd.hex()}")
            await gatttool_client.write_characteristic(
                rx_char['value_handle'], probe_cmd, response=False
            )
            await asyncio.sleep(0.5)
        
        await asyncio.sleep(2)
        
        log.info("DGT Pegasus protocol active")
        return True
    
    async def send_periodic_commands(self, gatttool_client) -> None:
        """Send periodic commands using gatttool client.
        
        Args:
            gatttool_client: GatttoolClient instance
        """
        if hasattr(self, '_rx_handle') and self._rx_handle:
            cmd = self.get_board_command()
            log.info("Sending periodic Pegasus board request")
            await gatttool_client.write_characteristic(
                self._rx_handle, cmd, response=False
            )
    
    def get_write_handle(self) -> int | None:
        """Return the write handle for gatttool operations."""
        return getattr(self, '_rx_handle', None)
    
    def get_read_handle(self) -> int | None:
        """Return the read/notify handle for gatttool operations."""
        return getattr(self, '_tx_handle', None)

