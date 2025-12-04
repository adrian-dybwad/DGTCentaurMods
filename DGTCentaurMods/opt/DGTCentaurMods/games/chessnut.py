# Chessnut Game Emulator
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

"""
Chessnut Air Protocol Emulator

Emulates a Chessnut Air chess board, responding to commands from chess apps
and generating board state updates based on the physical DGT Centaur board.

Protocol based on official Chessnut eBoards API documentation:
https://github.com/chessnutech/Chessnut_eBoards
"""

from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
from DGTCentaurMods.games.manager import EVENT_LIFT_PIECE, EVENT_PLACE_PIECE


# Chessnut Air command bytes
CMD_ENABLE_REPORTING = 0x21
CMD_BATTERY_REQUEST = 0x29
CMD_LED_CONTROL = 0x0a

# Chessnut Air response bytes
RESP_FEN_DATA = 0x01  # FEN notification header byte 0
RESP_BATTERY = 0x2a

# Piece encoding for Chessnut Air FEN format
# Index = piece code, value = FEN character
PIECE_TO_FEN = [
    None,  # 0: empty
    'q',   # 1: black queen
    'k',   # 2: black king
    'b',   # 3: black bishop
    'p',   # 4: black pawn
    'n',   # 5: black knight
    'R',   # 6: white rook
    'P',   # 7: white pawn
    'r',   # 8: black rook
    'B',   # 9: white bishop
    'N',   # 10: white knight
    'Q',   # 11: white queen
    'K',   # 12: white king
]

# Reverse mapping: FEN character to Chessnut piece code
FEN_TO_PIECE = {
    'q': 1, 'k': 2, 'b': 3, 'p': 4, 'n': 5,
    'R': 6, 'P': 7, 'r': 8, 'B': 9, 'N': 10, 'Q': 11, 'K': 12
}


class Chessnut:
    """Handles Chessnut Air protocol packets and commands.
    
    Emulates a Chessnut Air board by:
    - Responding to enable reporting command with FEN updates
    - Responding to battery level requests
    - Generating FEN notifications when board state changes
    
    Packet format:
    - Commands: [command_byte, length, payload...]
    - FEN notification: [0x01, 0x24, 32_bytes_position_data, ...]
    - Battery response: [0x2a, 0x02, battery_level, 0x00]
    """
    
    # Class property indicating whether this emulator supports RFCOMM (Bluetooth Classic)
    # Chessnut Air uses BLE only, not RFCOMM
    supports_rfcomm = False
    
    def __init__(self, sendMessage_callback=None, manager=None):
        """Initialize the Chessnut handler.
        
        Args:
            sendMessage_callback: Callback function(data) for sending messages
            manager: GameManager instance for board state
        """
        self.sendMessage = sendMessage_callback
        self.manager = manager
        self.buffer = []
        self.reporting_enabled = False
        self.last_fen = None
        
        # Simulated battery level (percentage)
        self._battery_level = 85
        self._is_charging = False
    
    def handle_manager_event(self, event, piece_event, field, time_in_seconds):
        """Handle game events from the manager.
        
        Generates FEN notifications when pieces are moved.
        
        Args:
            event: Event constant (EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_LIFT_PIECE, EVENT_PLACE_PIECE, etc.)
            piece_event: Raw board piece event (0=LIFT, 1=PLACE)
            field: Chess field index (0-63)
            time_in_seconds: Time in seconds since the start of the game
        """
        try:
            if not self.reporting_enabled:
                return
            
            # Generate FEN update on piece events
            if event in (EVENT_LIFT_PIECE, EVENT_PLACE_PIECE):
                self._send_fen_notification()
        except Exception as e:
            log.error(f"[Chessnut] Error in handle_manager_event: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_manager_move(self, move):
        """Handle moves from the manager.
        
        Args:
            move: Chess move object
        """
        try:
            log.info(f"[Chessnut] handle_manager_move: {move}")
            if self.reporting_enabled:
                self._send_fen_notification()
        except Exception as e:
            log.error(f"[Chessnut] Error in handle_manager_move: {e}")
            import traceback
            traceback.print_exc()
    
    def handle_manager_key(self, key):
        """Handle key presses from the manager.
        
        Args:
            key: Key that was pressed (board.Key enum value)
        """
        log.debug(f"[Chessnut] handle_manager_key: {key}")
    
    def handle_manager_takeback(self):
        """Handle takeback requests from the manager."""
        log.debug("[Chessnut] handle_manager_takeback")
        if self.reporting_enabled:
            self._send_fen_notification()
    
    # Valid Chessnut command bytes for protocol detection
    VALID_COMMANDS = {CMD_ENABLE_REPORTING, CMD_BATTERY_REQUEST, CMD_LED_CONTROL}
    
    def parse_byte(self, byte_value):
        """Parse one byte of incoming data.
        
        Accumulates bytes into buffer and processes complete commands.
        Only returns True when a complete valid Chessnut command is processed.
        Returns False while accumulating to allow other protocols to be tried
        during auto-detection.
        
        Args:
            byte_value: Raw byte value from wire
            
        Returns:
            True only when a complete valid Chessnut command was processed,
            False otherwise (including while accumulating)
        """
        self.buffer.append(byte_value)
        
        # Validate first byte is a known Chessnut command
        # This prevents claiming bytes from other protocols during auto-detection
        if self.buffer[0] not in self.VALID_COMMANDS:
            # Not a valid Chessnut command byte - clear buffer and reject
            self.buffer.clear()
            return False
        
        # Need at least 2 bytes: command, length
        if len(self.buffer) < 2:
            return False  # Accumulating, but don't claim ownership yet
        
        cmd = self.buffer[0]
        length = self.buffer[1]
        
        # Validate length is reasonable (prevent buffer overflow from bad data)
        # Chessnut commands typically have small payloads
        if length > 64:
            log.debug(f"[Chessnut] Invalid length {length} - clearing buffer")
            self.buffer.clear()
            return False
        
        # Check if we have the complete packet
        expected_length = 2 + length  # cmd + length + payload
        if len(self.buffer) < expected_length:
            return False  # Still accumulating, don't claim ownership yet
        
        # Process complete packet
        payload = self.buffer[2:expected_length]
        self.buffer = self.buffer[expected_length:]  # Remove processed bytes
        
        return self._handle_command(cmd, payload)
    
    def _handle_command(self, cmd, payload):
        """Handle a complete Chessnut command.
        
        Args:
            cmd: Command byte
            payload: Payload bytes (excluding cmd and length)
            
        Returns:
            True if command was recognized and handled, False otherwise
        """
        if cmd == CMD_ENABLE_REPORTING:
            log.info("[Chessnut] Enable reporting command received")
            self.reporting_enabled = True
            # Send initial FEN notification
            self._send_fen_notification()
            return True
        
        elif cmd == CMD_BATTERY_REQUEST:
            log.info("[Chessnut] Battery request command received")
            self._send_battery_response()
            return True
        
        elif cmd == CMD_LED_CONTROL:
            log.info(f"[Chessnut] LED control command received: {payload}")
            # LED control is acknowledged but not emulated
            return True
        
        else:
            log.warning(f"[Chessnut] Unknown command: 0x{cmd:02x}")
            return False
    
    def _get_board_fen(self):
        """Get current board position as FEN string.
        
        Returns:
            FEN position string (piece placement part only)
        """
        try:
            if self.manager and hasattr(self.manager, 'get_fen'):
                return self.manager.get_fen()
            
            # Fallback: get from board directly
            if hasattr(board, 'get_fen'):
                return board.get_fen()
            
            # Default starting position
            return "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
        except Exception as e:
            log.error(f"[Chessnut] Error getting board FEN: {e}")
            return "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    
    def _fen_to_chessnut_bytes(self, fen):
        """Convert FEN position string to Chessnut 32-byte format.
        
        Chessnut format:
        - 32 bytes for 64 squares (2 squares per byte)
        - Square order: h8 -> g8 -> f8 -> ... -> a8 -> h7 -> ... -> a1
        - Lower nibble = first square, higher nibble = next square
        
        Args:
            fen: FEN position string (piece placement part only)
            
        Returns:
            32-byte array representing the position
        """
        # Parse FEN into 8x8 board array
        # board_array[rank][file] where rank 0 = rank 8, file 0 = file a
        board_array = [[0] * 8 for _ in range(8)]
        
        ranks = fen.split('/')
        for rank_idx, rank_str in enumerate(ranks):
            file_idx = 0
            for char in rank_str:
                if char.isdigit():
                    file_idx += int(char)
                elif char in FEN_TO_PIECE:
                    board_array[rank_idx][file_idx] = FEN_TO_PIECE[char]
                    file_idx += 1
                else:
                    file_idx += 1  # Unknown piece, treat as empty
        
        # Convert to Chessnut 32-byte format
        # Square order: h8 -> g8 -> f8 -> ... -> a8 -> h7 -> ... -> a1
        result = bytearray(32)
        
        for row in range(8):  # rank 8 to rank 1
            for col in range(7, -1, -1):  # file h to a
                piece_code = board_array[row][7 - col]  # 7-col to reverse file order
                byte_idx = (row * 8 + (7 - col)) // 2
                
                if (7 - col) % 2 == 0:
                    # Lower nibble
                    result[byte_idx] = (result[byte_idx] & 0xF0) | (piece_code & 0x0F)
                else:
                    # Higher nibble
                    result[byte_idx] = (result[byte_idx] & 0x0F) | ((piece_code & 0x0F) << 4)
        
        return bytes(result)
    
    def _send_fen_notification(self):
        """Send FEN position notification to connected client."""
        if not self.sendMessage:
            return
        
        try:
            fen = self._get_board_fen()
            
            # Only send if FEN changed
            if fen == self.last_fen:
                return
            self.last_fen = fen
            
            # Build 36-byte FEN notification
            # Bytes 0-1: Header (0x01, 0x24 = 36 decimal)
            # Bytes 2-33: Position data (32 bytes)
            # Bytes 34-35: Reserved/checksum (0x00, 0x00)
            position_bytes = self._fen_to_chessnut_bytes(fen)
            
            notification = bytearray([RESP_FEN_DATA, 0x24])  # Header
            notification.extend(position_bytes)  # 32 bytes position
            notification.extend([0x00, 0x00])  # Reserved
            
            log.info(f"[Chessnut] Sending FEN notification: {fen}")
            log.debug(f"[Chessnut] FEN bytes: {notification.hex()}")
            
            self.sendMessage(bytes(notification))
        except Exception as e:
            log.error(f"[Chessnut] Error sending FEN notification: {e}")
            import traceback
            traceback.print_exc()
    
    def _send_battery_response(self):
        """Send battery level response to connected client."""
        if not self.sendMessage:
            return
        
        try:
            # Battery response format: [0x2a, 0x02, battery_level, 0x00]
            # battery_level bit 7 = charging flag, bits 0-6 = percentage
            battery_byte = self._battery_level & 0x7F
            if self._is_charging:
                battery_byte |= 0x80
            
            response = bytes([RESP_BATTERY, 0x02, battery_byte, 0x00])
            
            log.info(f"[Chessnut] Sending battery response: {self._battery_level}% (charging: {self._is_charging})")
            log.debug(f"[Chessnut] Battery bytes: {response.hex()}")
            
            self.sendMessage(response)
        except Exception as e:
            log.error(f"[Chessnut] Error sending battery response: {e}")
            import traceback
            traceback.print_exc()
    
    def reset(self):
        """Reset the parser state.
        
        Clears accumulated buffer and resets to initial state.
        """
        self.buffer = []
        self.reporting_enabled = False
        self.last_fen = None
        log.debug("[Chessnut] Parser reset")
    
    def set_battery_level(self, level, is_charging=False):
        """Set the simulated battery level.
        
        Args:
            level: Battery percentage (0-100)
            is_charging: Whether the battery is charging
        """
        self._battery_level = max(0, min(100, level))
        self._is_charging = is_charging

