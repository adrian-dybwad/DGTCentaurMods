# Pegasus Game
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

from DGTCentaurMods.board import board
from DGTCentaurMods.board.logging import log
from types import SimpleNamespace
import time


class Pegasus:
    """Handles Pegasus protocol packets and commands.
    
    Packet format:
    - Initial packet: 40 60 02 00 00 63 07 8e 87 b0 18 b6 f4 00 5a 47 42 44
    - Subsequent packets: <type> <length> <payload> <00 terminator>
    - Note: length byte includes payload + terminator (not including the length byte itself)
    """
    
    # Valid command types mapped to their names
    COMMANDS = {
        0x60: "LED_CONTROL",
        0x63: "DEVELOPER_KEY",
        0x40: "INITIAL_COMMAND",
        0x45: "SERIAL_NUMBER",
    }
    
    # Reverse mapping: name -> hex value
    COMMAND_BY_NAME = {name: hex_val for hex_val, name in COMMANDS.items()}
    
    # Export command hex values as constants (e.g., LED_CONTROL = 0x60)
    # Create namespace for accessing commands by name (e.g., command.LED_CONTROL -> 0x60)
    command = SimpleNamespace(**{name: hex_val for hex_val, name in COMMANDS.items()})
    
    def __init__(self, sendMessage_callback=None, manager=None):
        """Initialize the Pegasus handler.
        
        Args:
            sendMessage_callback: Optional callback function(data) for sending messages
            manager: Optional GameManager instance
        """
        self.buffer = []
        self.state = "WAITING_FOR_INITIAL"
        self.sendMessage = sendMessage_callback
        self.manager = manager
    
    def handle_manager_event(self, event):
        """Handle game events from the manager.
        
        Args:
            event: Event constant (EVENT_NEW_GAME, EVENT_WHITE_TURN, etc.)
        """
        log.info(f"[Pegasus] handle_manager_event called: event={event}")
    
    def handle_manager_move(self, move):
        """Handle moves from the manager.
        
        Args:
            move: Chess move object
        """
        log.info(f"[Pegasus] handle_manager_move called: move={move}")
    
    def handle_manager_key(self, key):
        """Handle key presses from the manager.
        
        Args:
            key: Key that was pressed (board.Key enum value)
        """
        log.info(f"[Pegasus] handle_manager_key called: key={key}")
    
    def handle_manager_takeback(self):
        """Handle takeback requests from the manager."""
        log.info(f"[Pegasus] handle_manager_takeback called")
    
    def begin(self):
        """Called when the initial packet sequence is received."""
        log.info("[Pegasus] Initial packet received, beginning protocol")
        self.state = "WAITING_FOR_PACKET"
        board.ledsOff()
    
    def led_control(self, payload):
        """Handle LED control packet.
        
        Args:
            payload: List of payload bytes
            
        Returns:
            True if handled successfully, False otherwise
        """
        # LEDS control from mobile app
        # Format: 96, [len-2], 5, speed, mode, intensity, fields..., 0
        log.info(f"[Pegasus LED packet] raw: {' '.join(f'{b:02x}' for b in payload)}")
        if payload[0] == 2:
            if payload[1] == 0 and payload[2] == 0:
                board.ledsOff()
                log.info("[Pegasus board] ledsOff() because mode==2")
            else:
                log.info("[Pegasus board] unsupported mode==2 but payload 1, 2 is not 00 00")
        elif payload[0] == 5:
            ledspeed_in = int(payload[1])
            mode = int(payload[2])
            intensity_in = int(payload[3])
            fields_hw = []
            for x in range(4, len(payload)):
                fields_hw.append(int(payload[x]))
            # Map Pegasus/firmware index to board API index
            def hw_to_board(i):
                return (7 - (i // 8)) * 8 + (i % 8)
            fields_board = [hw_to_board(f) for f in fields_hw]
            log.info(f"[Pegasus LED packet] speed_in={ledspeed_in} intensity_in={intensity_in}")
            # Scale intensity: intensity_in 10-0 maps to intensity 1,2,3,4,5,6,7,8,9,0
            # Formula: intensity = 11 - intensity_in, with special cases for 0 and 1
            if intensity_in == 0:
                intensity = 0
            elif intensity_in == 1:
                intensity = 0
            else:
                intensity = 11 - intensity_in
            # Clamp intensity to valid range 0-10
            intensity = max(0, min(10, intensity))
            ledspeed = max(1, min(100, ledspeed_in))
            log.info(f"[Pegasus LED packet] speed={ledspeed} mode={mode} intensity={intensity} hw={fields_hw} -> board={fields_board}")
            try:
                if len(fields_board) == 0:
                    board.ledsOff()
                    log.info("[Pegasus board] ledsOff()")
                elif len(fields_board) == 1:
                    board.led(fields_board[0], intensity=intensity, speed=ledspeed, repeat=0)
                    log.info(f"[Pegasus board] led({fields_board[0]})")
                else:
                    board.ledArray(fields_board, intensity=intensity, speed=ledspeed, repeat=0)
                    log.info(f"[Pegasus board] ledArray({fields_board}, intensity={intensity}) mode={mode}")
                    # if mode == 1:
                    #     time.sleep(0.5)
                    #     log.info("[Pegasus board] ledsOff() because mode==1")
                    #     board.ledsOff()
            except Exception as e:
                log.info(f"[Pegasus LED packet] error driving LEDs: {e}")
        else:
            log.info(f"[Pegasus LED packet] unsupported mode={payload[0]}")

        # Only return True is we sent anything back. Otherwise, let the caller handle it.
        return False
    
    def serial_number(self, payload):
        """Handle serial number packet.
        
        Args:
            payload: List of payload bytes
            
        Returns:
            True if handled successfully, False otherwise
        """
        log.info(f"[Pegasus Serial number] raw: {' '.join(f'{b:02x}' for b in payload)}")
        return False
    
    def handle_packet(self, packet_type, payload):
        """Handle a parsed packet.
        
        Args:
            packet_type: Packet type byte as integer
            payload: List of payload bytes
        """
        log.info(f"[Pegasus] Received packet: type=0x{packet_type:02X}, payload_len={len(payload)}, payload={' '.join(f'{b:02x}' for b in payload)}")
        if packet_type == self.command.DEVELOPER_KEY:
            # Developer key registration
            log.info(f"[Pegasus Developer key] raw: {' '.join(f'{b:02x}' for b in payload)}")
            return False
        elif packet_type == self.command.LED_CONTROL:
            return self.led_control(payload)
        elif packet_type == self.command.SERIAL_NUMBER:
            return self.serial_number(payload)
        else:
            log.info(f"[Pegasus] unsupported packet type={packet_type}")
            return False
    def parse_byte(self, byte_value):
        """Receive one byte and parse packet.
        
        Args:
            byte_value: Single byte value (0-255)
            
        Returns:
            True if a complete packet was received, False otherwise
        """
        try:
            if self.state == "WAITING_FOR_INITIAL":
                # Check if this byte matches the initial command
                if byte_value == self.command.INITIAL_COMMAND:
                    # Initial command received
                    self.begin()
                return True
            
            elif self.state == "WAITING_FOR_PACKET":
                # Add byte to buffer
                self.buffer.append(byte_value)
                
                # Limit buffer size to prevent unbounded growth (max reasonable packet size)
                max_buffer_size = 1000
                if len(self.buffer) > max_buffer_size:
                    log.warning(f"[Pegasus] Buffer too large ({len(self.buffer)} bytes), clearing")
                    self.buffer = []
                    return False
                
                # Check if we just received a 00 terminator
                if byte_value == 0x00:
                    # Look backwards from the 00 to find length and type
                    # Packet format: <type> <length> <payload> <00>
                    # Length includes payload + terminator
                    # So if 00 is at position N, length should be at position N - length
                    terminator_pos = len(self.buffer) - 1
                    
                    # Try to find a valid length byte by looking backwards
                    found_packet = False
                    for i in range(terminator_pos - 1, -1, -1):  # Start from position before 00, go backwards
                        candidate_length = self.buffer[i]
                        
                        # Check if this could be a length byte
                        # Length should equal: distance from length to terminator (including terminator)
                        # So: candidate_length == (terminator_pos - i)
                        if candidate_length == (terminator_pos - i):
                            # Found a potential length byte
                            # Type should be at position i - 1
                            if i > 0:
                                packet_type = int(self.buffer[i - 1])
                                
                                # Only accept packets with valid command types
                                if packet_type not in self.COMMANDS:
                                    # Not a valid command, continue looking backwards
                                    continue
                                
                                packet_length = int(candidate_length)
                                
                                # Payload is everything between length and terminator
                                payload_start = i + 1
                                payload_end = terminator_pos
                                payload = [int(b) for b in self.buffer[payload_start:payload_end]]
                                
                                # Orphaned bytes are everything before the type
                                orphaned_bytes = [int(b) for b in self.buffer[0:i-1]]
                                
                                # Log orphaned bytes if any
                                if orphaned_bytes:
                                    log.info(f"[Pegasus] ORPHANED bytes before packet: {' '.join(f'{b:02x}' for b in orphaned_bytes)}")
                                
                                # Log the command name
                                command_name = self.COMMANDS[packet_type]
                                log.debug(f"[Pegasus] Valid command detected: 0x{packet_type:02X} ({command_name})")
                                
                                # Clear buffer
                                self.buffer = []
                                
                                found_packet = True

                                # Handle the packet
                                self.handle_packet(packet_type, payload)
                                return True
                    
                    # If we didn't find a valid packet, keep the 00 in buffer and continue
                    # (might be part of a larger packet or noise)
                    if not found_packet:
                        # Could be a false 00, or packet not complete yet
                        # Keep accumulating but log if buffer gets large
                        if len(self.buffer) > 100:
                            log.debug(f"[Pegasus] No valid packet found after 00, buffer size: {len(self.buffer)}")
                
            return False
            
        except Exception as e:
            log.error(f"[Pegasus] Error parsing byte 0x{byte_value:02X}: {e}")
            import traceback
            traceback.print_exc()
            # Reset parser state on error
            if self.state == "WAITING_FOR_PACKET":
                self.buffer = []
            return False
    
    def reset(self):
        """Reset parser state."""
        self.buffer = []
        self.state = "WAITING_FOR_INITIAL"

