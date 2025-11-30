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

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.games.millennium import Millennium
from DGTCentaurMods.games.pegasus import Pegasus
from DGTCentaurMods.games.manager import GameManager
import chess


class Universal:
    """Universal game handler that supports multiple protocols (Millennium, Pegasus)."""
    
    def __init__(self, sendMessage_callback=None):
        """Initialize the Universal handler with Millennium and Pegasus parsers.
        
        Args:
            sendMessage_callback: Optional callback function(data) for sending messages
        """
        self.sendMessage = sendMessage_callback
        self.is_pegasus = False
        self.is_millennium = False
        self.manager = GameManager()
        self._millennium = Millennium(sendMessage_callback=sendMessage_callback, manager=self.manager)
        self._pegasus = Pegasus(sendMessage_callback=sendMessage_callback, manager=self.manager)
        self.subscribe_manager()
    
    def _manager_event_callback(self, event):
        """Handle game events from the manager.
        
        Args:
            event: Event constant (EVENT_NEW_GAME, EVENT_WHITE_TURN, etc.)
        """
        try:
            log.info(f"[Universal] Manager event: {event}")
            if self.is_millennium and hasattr(self._millennium, 'handle_manager_event'):
                self._millennium.handle_manager_event(event)
            elif self.is_pegasus and hasattr(self._pegasus, 'handle_manager_event'):
                self._pegasus.handle_manager_event(event)
        except Exception as e:
            log.error(f"[Universal] Error in manager event callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_move_callback(self, move):
        """Handle moves from the manager.
        
        Args:
            move: Chess move object
        """
        try:
            log.info(f"[Universal] Manager move: {move} is_millennium={self.is_millennium} is_pegasus={self.is_pegasus}")
            if self.is_millennium and hasattr(self._millennium, 'handle_manager_move'):
                self._millennium.handle_manager_move(move)
            elif self.is_pegasus and hasattr(self._pegasus, 'handle_manager_move'):
                self._pegasus.handle_manager_move(move)
        except Exception as e:
            log.error(f"[Universal] Error in manager move callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_key_callback(self, key):
        """Handle key presses from the manager.
        
        Args:
            key: Key that was pressed (board.Key enum value)
        """
        try:
            log.info(f"[Universal] Manager key: {key}")
            if self.is_millennium and hasattr(self._millennium, 'handle_manager_key'):
                self._millennium.handle_manager_key(key)
            elif self.is_pegasus and hasattr(self._pegasus, 'handle_manager_key'):
                self._pegasus.handle_manager_key(key)
        except Exception as e:
            log.error(f"[Universal] Error in manager key callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_takeback_callback(self):
        """Handle takeback requests from the manager."""
        try:
            log.info(f"[Universal] Manager takeback requested")
            if self.is_millennium and hasattr(self._millennium, 'handle_manager_takeback'):
                self._millennium.handle_manager_takeback()
            elif self.is_pegasus and hasattr(self._pegasus, 'handle_manager_takeback'):
                self._pegasus.handle_manager_takeback()
        except Exception as e:
            log.error(f"[Universal] Error in manager takeback callback: {e}")
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
            if not self.is_millennium:
                log.info("[Universal] Millennium protocol detected")
                self.is_millennium = True
            return True
        elif not self.is_millennium and self._pegasus.parse_byte(byte_value):
            if not self.is_pegasus:
                log.info("[Universal] Pegasus protocol detected")
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


    def subscribe_manager(self):
        """Subscribe to the game manager with callbacks."""
        try:
            log.info("[Universal] Subscribing to game manager")
            self.manager.subscribe_game(
                self._manager_event_callback,
                self._manager_move_callback,
                self._manager_key_callback,
                self._manager_takeback_callback
            )
            log.info("[Universal] Successfully subscribed to game manager")
        except Exception as e:
            log.error(f"[Universal] Failed to subscribe to game manager: {e}")
            import traceback
            traceback.print_exc()

