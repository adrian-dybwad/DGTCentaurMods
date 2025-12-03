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
    
    The Chessnut Air sends board position as a 32-byte array where each byte
    represents two squares (4 bits per square).
    
    Piece encoding (4 bits):
        0x0 = empty
        0x1 = white pawn
        0x2 = white rook
        0x3 = white knight
        0x4 = white bishop
        0x5 = white queen
        0x6 = white king
        0x7 = black pawn
        0x8 = black rook
        0x9 = black knight
        0xA = black bishop
        0xB = black queen
        0xC = black king
    
    Args:
        data: Raw bytes from FEN characteristic notification
        
    Returns:
        FEN position string (piece placement part only)
    """
    if len(data) < 32:
        return f"<incomplete data: {len(data)} bytes>"
    
    # Piece mapping from Chessnut encoding to FEN characters
    piece_map = {
        0x0: None,   # empty
        0x1: 'P',    # white pawn
        0x2: 'R',    # white rook
        0x3: 'N',    # white knight
        0x4: 'B',    # white bishop
        0x5: 'Q',    # white queen
        0x6: 'K',    # white king
        0x7: 'p',    # black pawn
        0x8: 'r',    # black rook
        0x9: 'n',    # black knight
        0xA: 'b',    # black bishop
        0xB: 'q',    # black queen
        0xC: 'k',    # black king
    }
    
    # Build the board array (8x8)
    board = []
    for i in range(32):
        byte = data[i]
        # Each byte contains two squares
        high_nibble = (byte >> 4) & 0x0F
        low_nibble = byte & 0x0F
        board.append(piece_map.get(high_nibble))
        board.append(piece_map.get(low_nibble))
        
    # Convert to FEN (rank 8 to rank 1)
    fen_rows = []
    for rank in range(7, -1, -1):  # 8th rank to 1st rank
        row = ""
        empty_count = 0
        for file in range(8):  # a to h
            square_idx = rank * 8 + file
            piece = board[square_idx]
            if piece is None:
                empty_count += 1
            else:
                if empty_count > 0:
                    row += str(empty_count)
                    empty_count = 0
                row += piece
        if empty_count > 0:
            row += str(empty_count)
        fen_rows.append(row)
    
    return "/".join(fen_rows)


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
        # Try to parse as FEN data (32+ bytes)
        if len(data) >= 32:
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
        
        Args:
            gatttool_client: GatttoolClient instance
        """
        import asyncio
        
        if hasattr(self, '_op_tx_handle') and self._op_tx_handle:
            cmd = self.get_enable_reporting_command()
            log.info("Sending periodic Chessnut enable reporting")
            await gatttool_client.write_characteristic(
                self._op_tx_handle, cmd, response=False
            )
            await asyncio.sleep(0.5)
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

