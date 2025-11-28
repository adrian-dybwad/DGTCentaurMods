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
import time


class Pegasus:
    """Handles Pegasus protocol packets and commands.
    
    Packet format:
    - Initial packet: 40 60 02 00 00 63 07 8e 87 b0 18 b6 f4 00 5a 47 42 44
    - Subsequent packets: <type> <length> <payload> <00 terminator>
    - Note: length byte includes payload + terminator (not including the length byte itself)
    """
    
    # Initial packet sequence
    # INITIAL_PACKET = bytes([# Android Chess includes these: 0x40, 0x60, 0x02, 0x00, 0x00, 
    #                         0x63, 0x07, 0x8e, 
    #                         0x87, 0xb0, 0x18, 0xb6, 0xf4, 0x00, 0x5a, 0x47, 
    #                         0x42, 0x44])
    INITIAL_PACKET = bytes([0x40])

    def __init__(self):
        """Initialize the Pegasus handler."""
        self.buffer = []
        self.state = "WAITING_FOR_INITIAL"
        self.initial_packet_index = 0
        self.packet_type = None
        self.packet_length = None
        self.payload = []
        self.expected_payload_length = 0
    
    def begin(self):
        """Called when the initial packet sequence is received."""
        log.info("[Pegasus] Initial packet received, beginning protocol")
        self.state = "WAITING_FOR_PACKET"
        board.ledsOff()
    
    def handle_packet(self, packet_type, payload):
        """Handle a parsed packet.
        
        Args:
            packet_type: Packet type byte as integer
            payload: List of payload bytes
        """
        log.info(f"[Pegasus] Received packet: type=0x{packet_type:02X}, payload_len={len(payload)}, payload={' '.join(f'{b:02x}' for b in payload)}")
        if packet_type == 99:
            # Developer key registration
            log.info(f"[Pegasus Developer key] raw: {' '.join(f'{b:02x}' for b in payload)}")
            return True
        elif packet_type == 96:
            # LEDS control from mobile app
            # Format: 96, [len-2], 5, speed, mode, intensity, fields..., 0
            log.info(f"[Pegasus LED packet] raw: {' '.join(f'{b:02x}' for b in payload)}")
            if payload[0] == 2:
                if payload[1] == 0 and payload[2] == 0:
                    board.ledsOff()
                    log.info("[Pegasus board] ledsOff() because mode==2")
                    return True
                else:
                    log.info("[Pegasus board] unsupported mode==2 but payload 1, 2 is not 00 00")
                    return False
            elif payload[0] == 5:
                ledspeed = int(payload[1])
                mode = int(payload[2])
                intensity_in = int(payload[3])
                fields_hw = []
                for x in range(4, len(payload)-1):
                    fields_hw.append(int(payload[x]))
                # Map Pegasus/firmware index to board API index
                def hw_to_board(i):
                    return (7 - (i // 8)) * 8 + (i % 8)
                fields_board = [hw_to_board(f) for f in fields_hw]
                log.info(f"[Pegasus LED packet] speed={ledspeed} mode={mode} intensity={intensity_in} hw={fields_hw} -> board={fields_board}")
                # Normalize intensity to 1..10 for board.* helpers
                intensity = max(1, min(10, intensity_in))
                try:
                    if len(fields_board) == 0:
                        board.ledsOff()
                        log.info("[Pegasus board] ledsOff()")
                    elif len(fields_board) == 1:
                        board.led(fields_board[0], intensity=intensity)
                        log.info(f"[Pegasus board] led({fields_board[0]})")
                    else:
                        board.ledArray(fields_board, intensity=intensity)
                        log.info(f"[Pegasus board] ledArray({fields_board}, intensity={intensity}) mode={mode}")
                        # if mode == 1:
                        #     time.sleep(0.5)
                        #     log.info("[Pegasus board] ledsOff() because mode==1")
                        #     board.ledsOff()
                    return True
                except Exception as e:
                    log.info(f"[Pegasus LED packet] error driving LEDs: {e}")
                    return False
            else:
                log.info(f"[Pegasus LED packet] unsupported mode={payload[0]}")
                return False
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
                # Check if this byte matches the expected byte in the initial packet
                if byte_value == self.INITIAL_PACKET[self.initial_packet_index]:
                    self.initial_packet_index += 1
                    # Check if we've received the complete initial packet
                    if self.initial_packet_index == len(self.INITIAL_PACKET):
                        # Initial packet complete
                        self.begin()
                        return True
                else:
                    # Byte doesn't match, reset to start of initial packet
                    self.initial_packet_index = 0
                    # Check if this byte could be the start of the initial packet
                    if byte_value == self.INITIAL_PACKET[0]:
                        self.initial_packet_index = 1
                return False
            
            elif self.state == "WAITING_FOR_PACKET":
                # We're waiting for a new packet: <type> <length> <payload> <00>
                if self.packet_type is None:
                    # Waiting for packet type
                    self.packet_type = byte_value
                    return False
                
                elif self.packet_length is None:
                    # Waiting for packet length
                    # Length includes payload + terminator (not including the length byte itself)
                    self.packet_length = byte_value
                    # Expected payload length is length - 1 (to account for the 00 terminator)
                    if self.packet_length > 0:
                        self.expected_payload_length = self.packet_length - 1
                    else:
                        # Length is 0, so no payload, just terminator
                        self.expected_payload_length = 0
                    self.payload = []
                    return False
                
                elif len(self.payload) < self.expected_payload_length:
                    # Collecting payload bytes
                    self.payload.append(byte_value)
                    return False
                
                else:
                    # We've collected all payload bytes, now waiting for 00 terminator
                    if byte_value == 0x00:
                        # Complete packet received
                        packet_type = self.packet_type
                        payload = self.payload.copy()
                        
                        # Reset state for next packet
                        self.packet_type = None
                        self.packet_length = None
                        self.payload = []
                        self.expected_payload_length = 0
                        
                        # Handle the packet
                        self.handle_packet(packet_type, payload)
                        return True
                    else:
                        # Invalid terminator, reset parser
                        log.warning(f"[Pegasus] Invalid packet terminator: expected 0x00, got 0x{byte_value:02X}, resetting parser")
                        self.packet_type = None
                        self.packet_length = None
                        self.payload = []
                        self.expected_payload_length = 0
                        return False
            
            return False
            
        except Exception as e:
            log.error(f"[Pegasus] Error parsing byte 0x{byte_value:02X}: {e}")
            import traceback
            traceback.print_exc()
            # Reset parser state on error
            self.packet_type = None
            self.packet_length = None
            self.payload = []
            self.expected_payload_length = 0
            if self.state == "WAITING_FOR_INITIAL":
                self.initial_packet_index = 0
            return False
    
    def reset(self):
        """Reset parser state."""
        self.buffer = []
        self.state = "WAITING_FOR_INITIAL"
        self.initial_packet_index = 0
        self.packet_type = None
        self.packet_length = None
        self.payload = []
        self.expected_payload_length = 0

