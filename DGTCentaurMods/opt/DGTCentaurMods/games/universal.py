# Millennium Game
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
from DGTCentaurMods.games.millennium import Millennium
from DGTCentaurMods.games.pegasus import Pegasus
import chess


class Universal:
    """Universal game handler that supports multiple protocols (Millennium, Pegasus)."""
    
    def __init__(self, sendMessage_callback=None):
        """Initialize the Universal handler with Millennium and Pegasus parsers.
        
        Args:
            sendMessage_callback: Optional callback function(data) for sending messages
        """
        self._millennium = Millennium(sendMessage_callback=sendMessage_callback)
        self._pegasus = Pegasus(sendMessage_callback=sendMessage_callback)
        self.sendMessage = sendMessage_callback
        self.is_pegasus = False
        self.is_millennium = False
    
    def _key_callback(self, key):
        """Handle key press events from the board.
        
        Args:
            key: The key that was pressed (board.Key enum value)
        """
        try:
            log.info(f"[Millennium] Key event: {key}")
        except Exception as e:
            log.error(f"[Millennium] Error in key callback: {e}")
            import traceback
            traceback.print_exc()

    def _field_callback(self, piece_event, field, time_in_seconds):
        """Handle field events (piece lift/place) from the board.
        
        Args:
            piece_event: 0 for LIFT, 1 for PLACE
            field: Chess square index (0=a1, 63=h8)
            time_in_seconds: Time from packet
        """
        try:
            event_type = "LIFT" if piece_event == 0 else "PLACE"
            field_name = chess.square_name(field)
            log.info(f"[Millennium] Field event: {event_type} on field {field} ({field_name}), time={time_in_seconds}")
        except Exception as e:
            log.error(f"[Millennium] Error in field callback: {e}")
            import traceback
            traceback.print_exc()

    def receive_data(self, byte_value):
        """Receive one byte of data and parse packet.
        
        This function implements a packet parser that handles:
        - Odd parity stripping (MSB parity bit)
        - ASCII payload accumulation
        - XOR CRC verification (last 2 ASCII hex digits)
        
        When a valid packet is received, it automatically calls the packet handler.
        
        Args:
            byte_value: Raw byte value from wire (with possible odd parity bit)
            
        Returns:
            Tuple (packet_type, payload, is_complete) where:
            - packet_type: First byte of payload (message type) as integer, or None
            - payload: List of ASCII character values (0-127), or None
            - is_complete: True if packet is complete and CRC valid, False otherwise
            
        Example:
            # Receive bytes one at a time
            for byte in byte_stream:
                packet_type, payload, is_complete = receive_data(byte)
                if is_complete:
                    # Packet handler is automatically called
                    log.info(f"Received packet type {packet_type}, payload: {payload}")
        """
        if not self.is_pegasus and self._millennium.parse_byte(byte_value):
            self.is_millennium = True
            return True
        elif not self.is_millennium and self._pegasus.parse_byte(byte_value):
            self.is_pegasus = True
            return True
        else:
            #is_millennium = False
            #is_pegasus = False
            return False

    def reset_parser(self):
        """Reset the packet parser state.
        
        Clears any accumulated buffer and resets parser to initial state.
        Useful when starting a new communication session or recovering from errors.
        """
        self._millennium.reset_parser()
        self._pegasus.reset()

    def subscribe(self):
        """Subscribe to board events and start logging."""
        try:
            log.info("[Millennium] Subscribing to board events")
            board.subscribeEvents(self._key_callback, self._field_callback, timeout=100000)
            log.info("[Millennium] Successfully subscribed to board events")
        except Exception as e:
            log.error(f"[Millennium] Failed to subscribe to board events: {e}")
            import traceback
            traceback.print_exc()

