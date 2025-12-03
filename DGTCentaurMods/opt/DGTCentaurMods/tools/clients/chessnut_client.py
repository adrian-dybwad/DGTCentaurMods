"""
Chessnut Air BLE Protocol Client

Provides protocol-specific handling for Chessnut Air chess boards using BLE.
Uses the generic BLEClient or GatttoolClient for low-level BLE operations.
"""

from typing import Callable

from DGTCentaurMods.board.logging import log


# Chessnut Air BLE UUIDs
CHESSNUT_FEN_RX_CHAR_UUID = "1b7e8262-2877-41c3-b46e-cf057c562023"  # Notify from board (FEN data)
CHESSNUT_OP_TX_CHAR_UUID = "1b7e8272-2877-41c3-b46e-cf057c562023"  # Write to board
CHESSNUT_OP_RX_CHAR_UUID = "1b7e8273-2877-41c3-b46e-cf057c562023"  # Notify from board (responses)

# Chessnut Air commands
CHESSNUT_ENABLE_REPORTING_CMD = bytes([0x21, 0x01, 0x00])
CHESSNUT_BATTERY_LEVEL_CMD = bytes([0x29, 0x01, 0x00])

# Required MTU for Chessnut Air (needs 500 bytes for full FEN data)
REQUIRED_MTU = 500


def parse_fen_data(data: bytes) -> str:
    """Parse FEN data from Chessnut Air notification.
    
    Based on official Chessnut eBoards API documentation:
    https://github.com/chessnutech/Chessnut_eBoards
    
    The notification is a 36-byte array:
    - Bytes [0-1]: Header
    - Bytes [2-33]: Position data (32 bytes, 64 squares)
    - Bytes [34-35]: Reserved/checksum
    
    Square order: h8 -> g8 -> f8 -> ... -> a8 -> h7 -> ... -> a1
    Each byte encodes two squares:
    - Lower 4 bits = first square (e.g., h8)
    - Higher 4 bits = next square (e.g., g8)
    
    Piece encoding (from official docs):
        0 = empty
        1 = black queen (q)
        2 = black king (k)
        3 = black bishop (b)
        4 = black pawn (p)
        5 = black knight (n)
        6 = white rook (R)
        7 = white pawn (P)
        8 = white rook (r) - docs say this but likely typo, treating as white rook
        9 = white bishop (B)
        10 = white knight (N)
        11 = white queen (Q)
        12 = white king (K)
    
    Args:
        data: Raw bytes from FEN characteristic notification (36 bytes expected)
        
    Returns:
        FEN position string (piece placement part only)
    """
    # Need at least 34 bytes (2 header + 32 position)
    if len(data) < 34:
        return f"<incomplete data: {len(data)} bytes>"
    
    # Piece mapping from official Chessnut docs
    # ['', 'q', 'k', 'b', 'p', 'n', 'R', 'P', 'r', 'B', 'N', 'Q', 'K']
    piece_map = [
        None,  # 0: empty
        'q',   # 1: black queen
        'k',   # 2: black king
        'b',   # 3: black bishop
        'p',   # 4: black pawn
        'n',   # 5: black knight
        'R',   # 6: white rook
        'P',   # 7: white pawn
        'r',   # 8: white rook (docs show lowercase, may be typo - using as black rook)
        'B',   # 9: white bishop
        'N',   # 10: white knight
        'Q',   # 11: white queen
        'K',   # 12: white king
    ]
    
    # Build FEN string following the official algorithm
    # Position data starts at byte 2
    fen = ""
    empty = 0
    
    for row in range(8):  # 8 rows (rank 8 to rank 1)
        for col in range(7, -1, -1):  # columns h to a (7 to 0)
            # Calculate byte index: each byte has 2 squares
            index = (row * 8 + col) // 2 + 2  # +2 for header offset
            
            # Lower nibble for even columns (h, f, d, b), higher for odd (g, e, c, a)
            if col % 2 == 0:
                piece_val = data[index] & 0x0F
            else:
                piece_val = (data[index] >> 4) & 0x0F
            
            # Get piece character
            piece = piece_map[piece_val] if piece_val < len(piece_map) else None
            
            if piece is None:
                empty += 1
            else:
                if empty > 0:
                    fen += str(empty)
                    empty = 0
                fen += piece
        
        # End of row
        if empty > 0:
            fen += str(empty)
            empty = 0
        if row < 7:
            fen += '/'
    
    return fen


def parse_battery_response(data: bytes) -> tuple[int, bool]:
    """Parse battery level response from Chessnut Air.
    
    Battery response format:
        Byte 0: 0x2a (response type)
        Byte 1: 0x02 (length)
        Byte 2: battery level (0-100, bit 7 = charging flag)
        Byte 3: checksum or unused
    
    Args:
        data: Raw bytes from Operation RX characteristic
        
    Returns:
        Tuple of (battery_percent, is_charging)
    """
    if len(data) >= 3 and data[0] == 0x2a and data[1] == 0x02:
        battery_byte = data[2]
        is_charging = (battery_byte & 0x80) != 0
        battery_percent = battery_byte & 0x7F
        return battery_percent, is_charging
    return -1, False


class ChessnutClient:
    """Protocol handler for Chessnut Air boards.
    
    Handles Chessnut-specific protocol encoding/decoding and provides
    methods for common operations like probing and sending commands.
    """
    
    def __init__(
        self,
        on_fen: Callable[[str], None] | None = None,
        on_battery: Callable[[int, bool], None] | None = None,
        on_data: Callable[[bytes], None] | None = None
    ):
        """Initialize the Chessnut client.
        
        Args:
            on_fen: Optional callback for FEN position updates
            on_battery: Optional callback for battery updates (percent, is_charging)
            on_data: Optional callback for raw data
        """
        self.on_fen = on_fen
        self.on_battery = on_battery
        self.on_data = on_data
        self._got_response = False
        self.last_fen: str = ""
        self.battery_level: int = -1
        self.is_charging: bool = False
        self.fen_char_uuid: str | None = None
        self.op_tx_char_uuid: str | None = None
        self.op_rx_char_uuid: str | None = None
    
    @property
    def fen_uuid(self) -> str:
        """Return the FEN characteristic UUID (notify)."""
        return CHESSNUT_FEN_RX_CHAR_UUID
    
    @property
    def op_tx_uuid(self) -> str:
        """Return the Operation TX characteristic UUID (write)."""
        return CHESSNUT_OP_TX_CHAR_UUID
    
    @property
    def op_rx_uuid(self) -> str:
        """Return the Operation RX characteristic UUID (notify)."""
        return CHESSNUT_OP_RX_CHAR_UUID
    
    def fen_notification_handler(self, sender, data: bytearray):
        """Handle notifications from FEN characteristic.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Chessnut FEN] ({len(data)} bytes): {hex_str}")
        
        self._got_response = True
        
        if self.on_data:
            self.on_data(bytes(data))
        
        # Parse and always log FEN position
        fen = parse_fen_data(bytes(data))
        log.info(f"FEN: {fen}")
        
        # Notify callback only on change
        if fen != self.last_fen:
            self.last_fen = fen
            if self.on_fen:
                self.on_fen(fen)
    
    def operation_notification_handler(self, sender, data: bytearray):
        """Handle notifications from Operation RX characteristic.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Chessnut Operation] ({len(data)} bytes): {hex_str}")
        
        self._got_response = True
        
        if self.on_data:
            self.on_data(bytes(data))
        
        # Check for battery level response
        battery, charging = parse_battery_response(bytes(data))
        if battery >= 0:
            self.battery_level = battery
            self.is_charging = charging
            charging_str = "Charging" if charging else "Not charging"
            log.info(f"Battery Level: {battery}% ({charging_str})")
            if self.on_battery:
                self.on_battery(battery, charging)
    
    def generic_notification_handler(self, sender, data: bytearray):
        """Handle notifications from any Chessnut characteristic.
        
        Used when we don't know which characteristic the data is from.
        Attempts to parse as FEN or battery data.
        
        Args:
            sender: The characteristic that sent the notification
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Chessnut] ({len(data)} bytes): {hex_str}")
        self._got_response = True
        
        if self.on_data:
            self.on_data(bytes(data))
        
        # Try to parse as known packet types
        self._parse_and_log_data(bytes(data))
    
    def gatttool_notification_handler(self, handle: int, data: bytearray):
        """Handle notifications when using gatttool backend.
        
        Args:
            handle: The characteristic handle
            data: The notification data
        """
        hex_str = ' '.join(f'{b:02x}' for b in data)
        log.info(f"RX [Chessnut] ({len(data)} bytes): {hex_str}")
        self._got_response = True
        
        if self.on_data:
            self.on_data(bytes(data))
        
        # Try to parse as known packet types
        self._parse_and_log_data(bytes(data))
    
    def _parse_and_log_data(self, data: bytes):
        """Parse data and log any recognized packet types.
        
        Attempts to parse the data as FEN or battery response and logs
        the parsed result.
        
        Args:
            data: Raw bytes from notification
        """
        # Try to parse as FEN data (36 bytes: 2 header + 32 position + 2 reserved)
        if len(data) >= 34:
            fen = parse_fen_data(data)
            log.info(f"FEN: {fen}")
            if fen != self.last_fen:
                self.last_fen = fen
                if self.on_fen:
                    self.on_fen(fen)
            return
        
        # Try to parse as battery response
        battery, charging = parse_battery_response(data)
        if battery >= 0:
            self.battery_level = battery
            self.is_charging = charging
            charging_str = "Charging" if charging else "Not charging"
            log.info(f"Battery: {battery}% ({charging_str})")
            if self.on_battery:
                self.on_battery(battery, charging)
            return
        
        # Try to identify other known packet types
        if len(data) >= 1:
            packet_type = data[0]
            if packet_type == 0x21:
                log.info("Packet type: Enable reporting ACK")
            elif packet_type == 0x22:
                log.info("Packet type: Board state request ACK")
            elif packet_type == 0x29:
                log.info("Packet type: Battery request (no response data)")
            else:
                log.info(f"Packet type: Unknown (0x{packet_type:02x})")
    
    def get_enable_reporting_command(self) -> bytes:
        """Return the command to enable board reporting.
        
        Returns:
            Command bytes
        """
        return CHESSNUT_ENABLE_REPORTING_CMD
    
    def get_battery_command(self) -> bytes:
        """Return the command to request battery level.
        
        Returns:
            Command bytes
        """
        return CHESSNUT_BATTERY_LEVEL_CMD
    
    def got_response(self) -> bool:
        """Check if a response was received since last reset.
        
        Returns:
            True if a response was received
        """
        return self._got_response
    
    def reset_response_flag(self):
        """Reset the response flag for the next probe."""
        self._got_response = False
    
    def check_mtu(self, mtu: int):
        """Check if MTU is sufficient and log warning if not.
        
        Args:
            mtu: The negotiated MTU size
        """
        if mtu < REQUIRED_MTU:
            log.warning(f"MTU ({mtu}) is less than required ({REQUIRED_MTU})")
            log.warning("FEN data may be truncated. Consider updating BlueZ config.")
    
    async def probe_with_bleak(self, ble_client) -> bool:
        """Probe for Chessnut Air protocol using bleak BLEClient.
        
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
        
        tx_uuid = find_char_uuid(self.op_tx_uuid)
        rx_uuid = find_char_uuid(self.op_rx_uuid)
        fen_uuid = find_char_uuid(self.fen_uuid)
        
        if not tx_uuid:
            log.info("Chessnut TX characteristic not found")
            return False
        
        log.info(f"Found Chessnut TX: {tx_uuid}")
        if rx_uuid:
            log.info(f"Found Chessnut RX: {rx_uuid}")
        if fen_uuid:
            log.info(f"Found Chessnut FEN: {fen_uuid}")
        
        # Store UUIDs for later use
        self._bleak_tx_uuid = tx_uuid
        self._bleak_rx_uuid = rx_uuid
        self._bleak_fen_uuid = fen_uuid
        self._ble_client = ble_client
        
        # Enable notifications
        if rx_uuid:
            await ble_client.start_notify(rx_uuid, self.operation_notification_handler)
        if fen_uuid:
            await ble_client.start_notify(fen_uuid, self.fen_notification_handler)
        
        # Send enable reporting command
        self.reset_response_flag()
        cmd = self.get_enable_reporting_command()
        log.info(f"Sending Chessnut enable reporting: {' '.join(f'{b:02x}' for b in cmd)}")
        
        if not await ble_client.write_characteristic(tx_uuid, cmd, response=False):
            log.warning("Failed to send Chessnut probe")
            return False
        
        # Wait for response
        for _ in range(30):  # 3 seconds
            await asyncio.sleep(0.1)
            if self.got_response():
                break
        
        # Check MTU
        if ble_client.mtu_size:
            self.check_mtu(ble_client.mtu_size)
        
        log.info("Chessnut Air protocol active")
        return True
    
    async def send_periodic_commands_bleak(self, ble_client) -> None:
        """Send periodic commands using bleak BLEClient.
        
        Only sends battery request periodically. Enable reporting is sent
        once during probe_with_bleak().
        
        Args:
            ble_client: BLEClient instance
        """
        if hasattr(self, '_bleak_tx_uuid') and self._bleak_tx_uuid:
            battery_cmd = self.get_battery_command()
            log.info("Sending periodic Chessnut battery request")
            await ble_client.write_characteristic(self._bleak_tx_uuid, battery_cmd, response=False)
    
    async def probe_with_gatttool(self, gatttool_client) -> bool:
        """Probe for Chessnut Air protocol using gatttool client.
        
        Args:
            gatttool_client: GatttoolClient instance
            
        Returns:
            True if protocol detected and initialized, False otherwise
        """
        import asyncio
        
        fen_char = gatttool_client.find_characteristic_by_uuid(self.fen_uuid)
        op_tx_char = gatttool_client.find_characteristic_by_uuid(self.op_tx_uuid)
        
        if not fen_char or not op_tx_char:
            log.info("Chessnut characteristics not found")
            return False
        
        log.info(f"Found Chessnut FEN RX: handle {fen_char['value_handle']:04x}")
        log.info(f"Found Chessnut OP TX: handle {op_tx_char['value_handle']:04x}")
        
        # Store handles for later use
        self._fen_handle = fen_char['value_handle']
        self._op_tx_handle = op_tx_char['value_handle']
        
        # Enable notifications on FEN characteristic
        await gatttool_client.enable_notifications(
            fen_char['value_handle'], self.gatttool_notification_handler
        )
        
        # Send enable reporting command
        self.reset_response_flag()
        cmd = self.get_enable_reporting_command()
        log.info(f"Sending Chessnut enable reporting: {cmd.hex()}")
        await gatttool_client.write_characteristic(
            op_tx_char['value_handle'], cmd, response=False
        )
        
        await asyncio.sleep(2)
        
        log.info("Chessnut Air protocol active")
        return True
    
    async def send_periodic_commands(self, gatttool_client) -> None:
        """Send periodic commands using gatttool client.
        
        Only sends battery request periodically. Enable reporting is sent
        once during probe_with_gatttool().
        
        Args:
            gatttool_client: GatttoolClient instance
        """
        if hasattr(self, '_op_tx_handle') and self._op_tx_handle:
            battery_cmd = self.get_battery_command()
            log.info("Sending periodic Chessnut battery request")
            await gatttool_client.write_characteristic(
                self._op_tx_handle, battery_cmd, response=False
            )
    
    def get_write_handle(self) -> int | None:
        """Return the write handle for gatttool operations."""
        return getattr(self, '_op_tx_handle', None)
    
    def get_read_handle(self) -> int | None:
        """Return the read/notify handle for gatttool operations."""
        return getattr(self, '_fen_handle', None)

