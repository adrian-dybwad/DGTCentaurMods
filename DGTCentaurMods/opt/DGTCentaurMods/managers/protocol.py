# Protocol Manager
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Manages protocol parsing and routing for chess app connections
# (Millennium, Pegasus, Chessnut). Bridges external protocols to GameManager.
#
# Player integrations are handled via the players/ module, which provides
# clean abstractions for different player types (Human, Engine, Lichess).
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

import time as _t
import logging as _log_temp
_logger = _log_temp.getLogger(__name__)
_s = _t.time()

from DGTCentaurMods.board.logging import log
_logger.debug(f"[protocol import] board.logging: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.emulators.millennium import Millennium
_logger.debug(f"[protocol import] millennium: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.emulators.pegasus import Pegasus
log.debug(f"[protocol import] pegasus: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.emulators.chessnut import Chessnut
log.debug(f"[protocol import] chessnut: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

from DGTCentaurMods.managers.game import GameManager, EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_BLACK_TURN
log.debug(f"[protocol import] game: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

# Import Player and Assistant managers
from DGTCentaurMods.players import PlayerManager
from DGTCentaurMods.managers.assistant import AssistantManager
from DGTCentaurMods.assistants import Suggestion, SuggestionType
log.debug(f"[protocol import] players/assistant managers: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

import chess
import threading
from typing import Optional
log.debug(f"[protocol import] stdlib: {(_t.time() - _s)*1000:.0f}ms")


class ProtocolManager:
    """Manages protocol parsing and routing for chess app connections.
    
    Supports Millennium, Pegasus, and Chessnut protocols. Auto-detects protocol
    from incoming data. Bridges external app protocols to GameManager.
    
    GameManager and PlayerManager are injected dependencies, not created here.
    """
    
    # Client type constants
    CLIENT_UNKNOWN = "unknown"
    CLIENT_MILLENNIUM = "millennium"
    CLIENT_PEGASUS = "pegasus"
    CLIENT_CHESSNUT = "chessnut"
    CLIENT_LICHESS = "lichess"
    
    def __init__(
        self,
        game_manager: GameManager,
        sendMessage_callback=None,
        client_type=None,
        compare_mode=False,
        display_update_callback=None,
        takeback_callback=None,
    ):
        """Initialize the ProtocolManager.
        
        Args:
            game_manager: The GameManager instance (required, injected dependency)
            sendMessage_callback: Callback function(data) for sending messages to client
            client_type: Hint about client type from BLE service UUID:
                        - CLIENT_MILLENNIUM: Millennium ChessLink
                        - CLIENT_PEGASUS: Nordic UART (Pegasus)
                        - CLIENT_CHESSNUT: Chessnut Air
                        - CLIENT_LICHESS: Lichess online play
                        - CLIENT_UNKNOWN or None: Auto-detect from incoming data (RFCOMM)
            compare_mode: If True, buffer emulator responses for comparison with
                         shadow host instead of sending directly. Used in relay mode.
            display_update_callback: Callback function(fen) for updating display with position
            takeback_callback: Callback function() called when a takeback is detected.
                              Used to sync analysis widget score history with game state.
        """
        self._sendMessage = sendMessage_callback
        self.compare_mode = compare_mode
        self._pending_response = None
        self._display_update_callback = display_update_callback
        self._takeback_callback = takeback_callback
        self._external_event_callback = None  # Optional callback for game events
        
        # Store the hint but don't trust it - always verify from data
        self._client_type_hint = client_type
        self.client_type = self.CLIENT_UNKNOWN
        
        # Protocol detection flags - only set True after data confirms protocol
        self.is_millennium = False
        self.is_pegasus = False
        self.is_chessnut = False
        self.is_lichess = False
        
        # Suggestion callback for assistants (Hand+Brain, hints, etc.)
        self._suggestion_callback = None
        
        # Player manager for white and black players
        self._player_manager: Optional[PlayerManager] = None
        
        # Assistant manager for Hand+Brain, hints, etc.
        self._assistant_manager: Optional[AssistantManager] = None
        
        # Game manager (injected dependency)
        self.game_manager = game_manager
        
        # Emulator instances - always create all emulators for auto-detection
        self._millennium = None
        self._pegasus = None
        self._chessnut = None
        
        # Create all emulators for auto-detection from actual data
        log.info(f"[ProtocolManager] Creating emulators for auto-detection (hint: {client_type or 'none'})")
        
        self._millennium = Millennium(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        log.debug("[ProtocolManager] Created Millennium emulator")
        
        self._pegasus = Pegasus(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        log.debug("[ProtocolManager] Created Pegasus emulator")
        
        self._chessnut = Chessnut(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        log.debug("[ProtocolManager] Created Chessnut emulator")
        
        self.subscribe_manager()
        
        log.info(f"[ProtocolManager] Initialized")
    
    def _setup_lichess_callbacks(self):
        """Set up callbacks for Lichess player."""
        from DGTCentaurMods.players import LichessPlayer
        
        for player in [self._player_manager.white_player, self._player_manager.black_player]:
            if isinstance(player, LichessPlayer):
                player.set_clock_callback(self._on_lichess_clock_update)
                player.set_game_info_callback(self._on_lichess_game_info)
    
    def _handle_emulator_response(self, data):
        """Handle response generated by an emulator.
        
        In compare_mode, buffers the response for later comparison with shadow host.
        Otherwise, sends directly to the client.
        
        Args:
            data: Response data bytes from emulator
        """
        if self.compare_mode:
            self._pending_response = bytes(data) if data else None
            log.debug(f"[ProtocolManager] Emulator response buffered ({len(data) if data else 0} bytes)")
        else:
            if self._sendMessage:
                self._sendMessage(data)
    
    @property
    def is_two_player_mode(self) -> bool:
        """Check if the game is in 2-player mode (both players are human).
        
        Returns:
            True if 2-player mode (human vs human), False otherwise
        """
        if self._player_manager:
            return self._player_manager.is_two_human
        return True
    
    @property
    def player_manager(self) -> Optional[PlayerManager]:
        """Get the player manager."""
        return self._player_manager
    
    def set_player_manager(self, player_manager: PlayerManager) -> None:
        """Set the player manager.
        
        Args:
            player_manager: The PlayerManager instance
        """
        self._player_manager = player_manager
        self.game_manager.set_player_manager(player_manager)
        
        # Check if this is a Lichess game
        from DGTCentaurMods.players import LichessPlayer
        is_lichess = any(isinstance(p, LichessPlayer) 
                        for p in [player_manager.white_player, player_manager.black_player])
        if is_lichess:
            self.client_type = self.CLIENT_LICHESS
            self.is_lichess = True
            self._setup_lichess_callbacks()
        
        log.info(f"[ProtocolManager] PlayerManager set: White={player_manager.white_player.name}, Black={player_manager.black_player.name}")
    
    def set_suggestion_callback(self, callback) -> None:
        """Set the suggestion callback for Hand+Brain hints.
        
        Args:
            callback: Function(piece_symbol, squares) called with suggestion
        """
        self._suggestion_callback = callback
    
    # =========================================================================
    # GameManager Callback Delegation (Law of Demeter compliance)
    # =========================================================================
    
    def set_on_terminal_position(self, callback):
        """Set callback for terminal positions. Callback(result, termination)."""
        self.game_manager.on_terminal_position = callback
    
    def set_on_back_pressed(self, callback):
        """Set callback for BACK button during game. Callback()."""
        self.game_manager.on_back_pressed = callback
    
    def set_on_kings_in_center(self, callback):
        """Set callback for kings-in-center gesture. Callback()."""
        self.game_manager.on_kings_in_center = callback
    
    def set_on_kings_in_center_cancel(self, callback):
        """Set callback when kings-in-center gesture is cancelled. Callback()."""
        self.game_manager.on_kings_in_center_cancel = callback
    
    def set_on_king_lift_resign(self, callback):
        """Set callback for king-lift resign gesture. Callback(color)."""
        self.game_manager.on_king_lift_resign = callback
    
    def set_on_king_lift_resign_cancel(self, callback):
        """Set callback to cancel king-lift resign. Callback()."""
        self.game_manager.on_king_lift_resign_cancel = callback
    
    def set_display_bridge(self, bridge) -> None:
        """Set the display bridge for consolidated display operations.
        
        The DisplayBridge provides a unified interface for all display-related
        operations including clock times, eval scores, alerts, and position updates.
        
        Args:
            bridge: Object implementing the DisplayBridge protocol
        """
        self.game_manager.display_bridge = bridge

    def set_on_promotion_needed(self, callback):
        """Set callback for promotion selection. Callback(is_white) -> piece_symbol."""
        self.game_manager.on_promotion_needed = callback
    
    # =========================================================================
    # GameManager Action Methods (Law of Demeter compliance)
    # =========================================================================
    
    def handle_resign(self, color=None):
        """Handle a resignation.
        
        Args:
            color: chess.WHITE or chess.BLACK, or None for current player
        """
        self.game_manager.handle_resign(color)
        
        # Notify players of resignation
        if self._player_manager:
            resign_color = color if color is not None else self.game_manager.chess_board.turn
            self._player_manager.white_player.on_resign(resign_color)
            self._player_manager.black_player.on_resign(resign_color)
    
    def handle_draw(self):
        """Handle a draw agreement."""
        self.game_manager.handle_draw()
    
    def handle_flag(self, color: str):
        """Handle time expiration (flag) for a player.
        
        Args:
            color: 'white' or 'black' - the player whose time expired
        """
        losing_color = chess.WHITE if color == 'white' else chess.BLACK
        self.game_manager.handle_flag(losing_color)
    
    def get_pending_response(self):
        """Get and clear the pending emulator response.
        
        Used in compare_mode to retrieve the buffered response for comparison.
        
        Returns:
            The buffered response bytes, or None if no response pending
        """
        response = self._pending_response
        self._pending_response = None
        return response
    
    def compare_with_shadow(self, shadow_response):
        """Compare shadow host response with emulator response.
        
        Args:
            shadow_response: Response bytes from shadow host
            
        Returns:
            Tuple (match, emulator_response) where:
            - match: True if responses match, False if different, None if no emulator response
            - emulator_response: The emulator's response bytes (for logging)
        """
        emulator_response = self.get_pending_response()
        
        if emulator_response is None:
            log.debug("[ProtocolManager] No emulator response to compare (emulator may not have generated one)")
            return (None, None)
        
        shadow_bytes = bytes(shadow_response) if shadow_response else b''
        match = emulator_response == shadow_bytes
        
        if not match:
            log.warning("[ProtocolManager] Response MISMATCH between emulator and shadow host:")
            log.warning(f"  Shadow host: {shadow_bytes.hex() if shadow_bytes else '(empty)'}")
            log.warning(f"  Emulator:    {emulator_response.hex() if emulator_response else '(empty)'}")
        else:
            log.debug(f"[ProtocolManager] Response match: {shadow_bytes.hex()}")
        
        return (match, emulator_response)
    
    def _manager_event_callback(self, event, piece_event=None, field=None, time_in_seconds=None):
        """Handle game events from the manager.
        
        Routes events to the active emulator based on detected protocol.
        Before protocol is confirmed, forwards to ALL emulators so that
        whichever one is active will respond correctly.
        
        Also handles player turn and assistant suggestion triggers.
        
        Args:
            event: Event constant (EVENT_NEW_GAME, EVENT_WHITE_TURN, etc.)
            piece_event: Piece event type
            field: Chess field index
            time_in_seconds: Time since game start
        """
        try:
            log.debug(f"[ProtocolManager] _manager_event_callback: {event} piece_event={piece_event}, field={field}")
            log.debug(f"[ProtocolManager] Flags: is_millennium={self.is_millennium}, is_pegasus={self.is_pegasus}, is_chessnut={self.is_chessnut}, is_lichess={self.is_lichess}")
            
            # Route to byte-stream emulators if connected
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_event'):
                log.debug("[ProtocolManager] Routing event to Millennium")
                self._millennium.handle_manager_event(event, piece_event, field, time_in_seconds)
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_event'):
                log.debug("[ProtocolManager] Routing event to Pegasus")
                self._pegasus.handle_manager_event(event, piece_event, field, time_in_seconds)
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_event'):
                log.debug("[ProtocolManager] Routing event to Chessnut")
                self._chessnut.handle_manager_event(event, piece_event, field, time_in_seconds)
            elif not self.is_lichess:
                # Protocol not yet confirmed - forward to ALL emulators
                log.debug("[ProtocolManager] Protocol not confirmed, forwarding event to all emulators")
                if self._millennium and hasattr(self._millennium, 'handle_manager_event'):
                    self._millennium.handle_manager_event(event, piece_event, field, time_in_seconds)
                if self._pegasus and hasattr(self._pegasus, 'handle_manager_event'):
                    self._pegasus.handle_manager_event(event, piece_event, field, time_in_seconds)
                if self._chessnut and hasattr(self._chessnut, 'handle_manager_event'):
                    self._chessnut.handle_manager_event(event, piece_event, field, time_in_seconds)
            
            # Handle player and assistant events
            if event == EVENT_NEW_GAME:
                self._handle_new_game()
                # Request first move for engine vs engine games
                self._request_current_player_move()
                self._check_assistant_suggestion()
            elif event == EVENT_WHITE_TURN or event == EVENT_BLACK_TURN:
                # Turn events are triggered AFTER the move is confirmed
                self._request_current_player_move()
                self._check_assistant_suggestion()
            
            # Notify external event callback
            if self._external_event_callback:
                try:
                    self._external_event_callback(event)
                except Exception as e:
                    log.debug(f"[ProtocolManager] Error in external event callback: {e}")
            
            # Update display with current position
            self._update_display()
        except Exception as e:
            log.error(f"[ProtocolManager] Error in _manager_event_callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_move_callback(self, move):
        """Handle moves from the manager.
        
        Forwards to byte-stream emulators and notifies players of moves.
        
        Args:
            move: Chess move object
        """
        try:
            log.debug(f"[ProtocolManager] _manager_move_callback: {move}")
            
            # Route to byte-stream emulators
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_move'):
                self._millennium.handle_manager_move(move)
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_move'):
                self._pegasus.handle_manager_move(move)
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_move'):
                self._chessnut.handle_manager_move(move)
            elif not self.is_lichess:
                # Protocol not yet confirmed - forward to ALL emulators
                log.debug("[ProtocolManager] Protocol not confirmed, forwarding move to all emulators")
                if self._millennium and hasattr(self._millennium, 'handle_manager_move'):
                    self._millennium.handle_manager_move(move)
                if self._pegasus and hasattr(self._pegasus, 'handle_manager_move'):
                    self._pegasus.handle_manager_move(move)
                if self._chessnut and hasattr(self._chessnut, 'handle_manager_move'):
                    self._chessnut.handle_manager_move(move)
            
            # Notify players of the move
            if self._player_manager:
                chess_move = chess.Move.from_uci(str(move)) if not isinstance(move, chess.Move) else move
                self._player_manager.on_move_made(chess_move, self.game_manager.chess_board)
            
            # Update display with current position
            self._update_display()
        except Exception as e:
            log.error(f"[ProtocolManager] Error in _manager_move_callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_key_callback(self, key):
        """Handle key presses forwarded from GameManager.
        
        Forwards key events to active byte-stream emulators.
        
        Args:
            key: Key that was pressed (board.Key enum value)
        """
        try:
            log.debug(f"[ProtocolManager] _manager_key_callback: {key}")
            
            # Forward to active byte-stream emulator
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_key'):
                self._millennium.handle_manager_key(key)
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_key'):
                self._pegasus.handle_manager_key(key)
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_key'):
                self._chessnut.handle_manager_key(key)
        except Exception as e:
            log.error(f"[ProtocolManager] Error in _manager_key_callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_takeback_callback(self):
        """Handle takeback requests from the manager."""
        try:
            log.info("[ProtocolManager] _manager_takeback_callback")
            
            # Notify display to sync analysis history with game state
            if self._takeback_callback:
                self._takeback_callback()
            
            # Notify players of takeback
            if self._player_manager:
                self._player_manager.on_takeback(self.game_manager.chess_board)

            # Notify assistant manager of takeback
            if self._assistant_manager:
                self._assistant_manager.on_takeback(self.game_manager.chess_board)
            
            # Forward to byte-stream emulators
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_takeback'):
                self._millennium.handle_manager_takeback()
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_takeback'):
                self._pegasus.handle_manager_takeback()
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_takeback'):
                self._chessnut.handle_manager_takeback()
        except Exception as e:
            log.error(f"[ProtocolManager] Error in _manager_takeback_callback: {e}")
            import traceback
            traceback.print_exc()

    def receive_key(self, key_id):
        """Receive a key event from the app coordinator and forward to GameManager.
        
        This is called by universal.py when it receives key events from the board.
        The event is forwarded to GameManager which handles game-related key logic.
        
        Args:
            key_id: Key identifier (board.Key enum value)
        """
        if self.game_manager:
            self.game_manager.receive_key(key_id)
    
    def receive_field(self, piece_event: int, field: int, time_in_seconds: float):
        """Receive a field event from the app coordinator and forward to GameManager.
        
        This is called by universal.py when it receives field events from the board.
        The event is forwarded to GameManager which handles piece detection logic.
        
        Args:
            piece_event: 0 = lift, 1 = place
            field: Board field index (0-63)
            time_in_seconds: Event timestamp
        """
        if self.game_manager:
            self.game_manager.receive_field(piece_event, field, time_in_seconds)

    def receive_data(self, byte_value):
        """Receive one byte of data and route to appropriate emulator.
        
        Auto-detects protocol from actual data. If a client_type hint was provided
        at construction (from BLE service UUID), that protocol is tried first.
        Once a protocol is detected, unused emulators are freed to save memory.
        
        Args:
            byte_value: Raw byte value from wire
            
        Returns:
            True if byte was successfully parsed, False otherwise
        """
        # If already detected, route directly to that emulator
        if self.is_millennium and self._millennium:
            return self._millennium.parse_byte(byte_value)
        elif self.is_pegasus and self._pegasus:
            return self._pegasus.parse_byte(byte_value)
        elif self.is_chessnut and self._chessnut:
            return self._chessnut.parse_byte(byte_value)
        
        # Auto-detect: try emulators in priority order based on hint
        emulators_to_try = []
        
        if self._client_type_hint == self.CLIENT_MILLENNIUM:
            emulators_to_try = [
                (self._millennium, "Millennium", self.CLIENT_MILLENNIUM),
                (self._pegasus, "Pegasus", self.CLIENT_PEGASUS),
                (self._chessnut, "Chessnut", self.CLIENT_CHESSNUT),
            ]
        elif self._client_type_hint == self.CLIENT_PEGASUS:
            emulators_to_try = [
                (self._pegasus, "Pegasus", self.CLIENT_PEGASUS),
                (self._millennium, "Millennium", self.CLIENT_MILLENNIUM),
                (self._chessnut, "Chessnut", self.CLIENT_CHESSNUT),
            ]
        elif self._client_type_hint == self.CLIENT_CHESSNUT:
            emulators_to_try = [
                (self._chessnut, "Chessnut", self.CLIENT_CHESSNUT),
                (self._millennium, "Millennium", self.CLIENT_MILLENNIUM),
                (self._pegasus, "Pegasus", self.CLIENT_PEGASUS),
            ]
        else:
            emulators_to_try = [
                (self._millennium, "Millennium", self.CLIENT_MILLENNIUM),
                (self._pegasus, "Pegasus", self.CLIENT_PEGASUS),
                (self._chessnut, "Chessnut", self.CLIENT_CHESSNUT),
            ]
        
        for emulator, name, client_type in emulators_to_try:
            if emulator and emulator.parse_byte(byte_value):
                hint_match = " (matches hint)" if self._client_type_hint == client_type else ""
                hint_mismatch = f" (hint was {self._client_type_hint})" if self._client_type_hint and self._client_type_hint != client_type else ""
                log.info(f"[ProtocolManager] {name} protocol detected via auto-detection{hint_match}{hint_mismatch}")
                
                self.client_type = client_type
                
                if client_type == self.CLIENT_MILLENNIUM:
                    self.is_millennium = True
                    self._pegasus = None
                    self._chessnut = None
                elif client_type == self.CLIENT_PEGASUS:
                    self.is_pegasus = True
                    self._millennium = None
                    self._chessnut = None
                elif client_type == self.CLIENT_CHESSNUT:
                    self.is_chessnut = True
                    self._millennium = None
                    self._pegasus = None
                
                return True
        
        return False

    def reset_parser(self):
        """Reset the packet parser state for all active emulators."""
        if self._millennium:
            self._millennium.reset_parser()
        if self._pegasus:
            self._pegasus.reset()
        if self._chessnut:
            self._chessnut.reset()

    def _update_display(self):
        """Update the e-paper display with the current board position."""
        if self._display_update_callback and self.game_manager:
            try:
                fen = self.game_manager.chess_board.fen()
                self._display_update_callback(fen)
            except Exception as e:
                log.error(f"[ProtocolManager] Error updating display: {e}")

    def subscribe_manager(self):
        """Subscribe to the game manager with callbacks."""
        try:
            log.info("[ProtocolManager] Subscribing to game manager")
            self.game_manager.subscribe_game(
                self._manager_event_callback,
                self._manager_move_callback,
                self._manager_key_callback,
                self._manager_takeback_callback
            )
            log.info("[ProtocolManager] Successfully subscribed to game manager")
        except Exception as e:
            log.error(f"[ProtocolManager] Failed to subscribe to game manager: {e}")
            import traceback
            traceback.print_exc()
    
    # =========================================================================
    # Player Management
    # =========================================================================
    
    def start_players(self) -> bool:
        """Start all configured players.
        
        Returns:
            True if all players started successfully.
        """
        if self._player_manager:
            return self._player_manager.start()
        return False
    
    def stop_players(self) -> None:
        """Stop all players and release resources."""
        if self._player_manager:
            self._player_manager.stop()
    
    def _on_player_move(self, move: chess.Move):
        """Handle move from a non-human player (engine, Lichess).
        
        This is called when a player provides a move (via PlayerManager).
        Routes to GameManager as a forced move.
        
        Args:
            move: The player's move.
        """
        # Don't execute engine moves if a Bluetooth app is connected
        # (except for Lichess which is a different kind of connection)
        if self.is_app_connected() and not self.is_lichess:
            log.info(f"[ProtocolManager] Ignoring player move {move.uci()} - external app is connected")
            return
        
        log.info(f"[ProtocolManager] Player move received: {move.uci()}")
        self.game_manager.computer_move(move.uci(), forced=True)
    
    def _handle_new_game(self):
        """Handle new game event - notify players and assistants."""
        if self._player_manager:
            self._player_manager.on_new_game()
        if self._assistant_manager:
            self._assistant_manager.on_new_game()
    
    def _on_all_players_ready(self):
        """Handle all players becoming ready.
        
        Called by PlayerManager when both players are ready.
        Triggers the first move request if White is not human.
        """
        from DGTCentaurMods.players import PlayerType
        
        if not self._player_manager:
            return
        
        white_player = self._player_manager.get_player(chess.WHITE)
        if white_player.player_type != PlayerType.HUMAN:
            log.info("[ProtocolManager] All players ready, requesting first move from White")
            self._request_current_player_move()
        else:
            log.debug("[ProtocolManager] All players ready, waiting for human to move")
    
    def _request_current_player_move(self):
        """Request a move from the current player.
        
        Called when turn changes. For human players, does nothing.
        For engines/Lichess, starts move computation.
        """
        if self.is_app_connected() and not self.is_lichess:
            return  # External app is connected, it handles moves
        
        if not self._player_manager:
            return
        
        if not self._player_manager.is_ready:
            return
        
        chess_board = self.game_manager.chess_board
        
        if chess_board.is_game_over():
            return
        
        log.debug("[ProtocolManager] Requesting move from current player")
        self._player_manager.request_move(chess_board)
    
    # =========================================================================
    # Assistant Management
    # =========================================================================
    
    def set_assistant_manager(self, assistant_manager: AssistantManager):
        """Set the assistant manager for suggestions (Hand+Brain, hints).
        
        Args:
            assistant_manager: The AssistantManager instance.
        """
        self._assistant_manager = assistant_manager
        
        # Wire suggestion callback
        assistant_manager.set_suggestion_callback(self._on_assistant_suggestion)
    
    def _on_assistant_suggestion(self, suggestion: Suggestion):
        """Handle suggestion from assistant (Hand+Brain).
        
        Args:
            suggestion: The assistant's suggestion.
        """
        if suggestion.suggestion_type == SuggestionType.PIECE_TYPE:
            log.info(f"[ProtocolManager] Suggestion: piece type {suggestion.piece_type} (squares: {suggestion.squares})")
            if self._suggestion_callback:
                self._suggestion_callback(suggestion.piece_type or "", suggestion.squares)
        elif suggestion.suggestion_type == SuggestionType.MOVE:
            log.info(f"[ProtocolManager] Suggestion: move {suggestion.move.uci() if suggestion.move else 'none'}")
    
    def _check_assistant_suggestion(self):
        """Check if assistant should provide a suggestion.
        
        Called when turn changes. For auto-suggest assistants (like Hand+Brain),
        requests a suggestion when it's the player's turn.
        """
        if not self._assistant_manager:
            return
        
        if not self._assistant_manager.is_active:
            return
        
        if not self._assistant_manager.auto_suggest:
            return
        
        chess_board = self.game_manager.chess_board
        
        # Only show suggestions for human players (they need to decide a move)
        # Engine/Lichess players already know what move to make
        if self._player_manager:
            from DGTCentaurMods.players import PlayerType
            current_player = self._player_manager.get_current_player(chess_board)
            if current_player.player_type != PlayerType.HUMAN:
                self._assistant_manager.clear_suggestion()
                return
        
        if chess_board.is_game_over():
            return
        
        log.debug("[ProtocolManager] Requesting suggestion from assistant manager")
        self._assistant_manager.request_suggestion(chess_board, chess_board.turn)
    
    # =========================================================================
    # Lichess-Specific Methods
    # =========================================================================
    
    def _on_lichess_clock_update(self, white_time: int, black_time: int):
        """Handle clock update from Lichess.
        
        Args:
            white_time: White's remaining time in seconds.
            black_time: Black's remaining time in seconds.
        """
        if self.game_manager:
            self.game_manager.set_clock(white_time, black_time)
    
    def _on_lichess_game_info(self, white_player: str, white_rating: str,
                               black_player: str, black_rating: str):
        """Handle game info update from Lichess.
        
        Args:
            white_player: White player's username.
            white_rating: White player's rating.
            black_player: Black player's username.
            black_rating: Black player's rating.
        """
        if self.game_manager:
            white_str = f"{white_player}({white_rating})"
            black_str = f"{black_player}({black_rating})"
            self.game_manager.set_game_info("", "", "", white_str, black_str)
    
    def start_lichess(self) -> bool:
        """Start the Lichess connection and game.
        
        Returns:
            True if Lichess started successfully, False on error.
        """
        return self.start_players()
    
    def stop_lichess(self):
        """Stop the Lichess connection."""
        self.stop_players()
    
    def is_lichess_connected(self) -> bool:
        """Check if Lichess game is active.
        
        Returns:
            True if connected to a Lichess game, False otherwise.
        """
        if self._player_manager and self.is_lichess:
            return self._player_manager.is_ready
        return False
    
    @property
    def lichess_board_flip(self) -> bool:
        """Get board flip state for Lichess (True if local human plays black).
        
        Returns:
            True if board should be flipped (playing as black).
        """
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            # Check which player is Lichess and return its board_flip
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    return player.board_flip
        return False
    
    def set_lichess_on_game_connected(self, callback):
        """Set callback for when Lichess game is connected and ready.
        
        Args:
            callback: Function to call when game transitions to playing.
        """
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.set_on_game_connected(callback)
    
    def lichess_resign(self):
        """Resign the current Lichess game."""
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.on_resign(chess.WHITE)  # Lichess handles the actual resign
                    return
    
    def lichess_abort(self):
        """Abort the current Lichess game."""
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.abort_game()
                    return
    
    def lichess_offer_draw(self):
        """Offer a draw in the current Lichess game."""
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.on_draw_offer()
                    return
    
    def set_lichess_game_over_callback(self, callback):
        """Set callback for Lichess game over events.
        
        Args:
            callback: Function(result, termination, winner) called when game ends.
        """
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.set_game_over_callback(callback)
    
    def set_lichess_takeback_offer_callback(self, callback):
        """Set callback for Lichess takeback offers from opponent.
        
        Args:
            callback: Function(accept_fn, decline_fn) called when opponent offers takeback.
        """
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.set_takeback_offer_callback(callback)
    
    def set_lichess_draw_offer_callback(self, callback):
        """Set callback for Lichess draw offers from opponent.
        
        Args:
            callback: Function(accept_fn, decline_fn) called when opponent offers draw.
        """
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.set_draw_offer_callback(callback)
    
    def set_lichess_info_message_callback(self, callback):
        """Set callback for Lichess informational messages.
        
        Args:
            callback: Function(message) called with info messages to display.
        """
        from DGTCentaurMods.players import LichessPlayer
        
        if self._player_manager:
            for player in [self._player_manager.white_player, self._player_manager.black_player]:
                if isinstance(player, LichessPlayer):
                    player.set_info_message_callback(callback)
    
    # =========================================================================
    # App Connection Management
    # =========================================================================
    
    def is_app_connected(self) -> bool:
        """Check if any chess app protocol has been detected.
        
        Returns:
            True if a chess app is connected (Millennium, Pegasus, Chessnut, or Lichess)
        """
        return self.is_millennium or self.is_pegasus or self.is_chessnut or self.is_lichess

    def on_app_connected(self):
        """Called when an app connects - pause local player moves."""
        log.info("[ProtocolManager] App connected - local players paused")
        
        # Clear any pending engine moves so they don't interfere
        if self._player_manager:
            self._player_manager.clear_pending_moves()
    
    def on_app_disconnected(self):
        """Called when app disconnects - resume local players."""
        log.info("[ProtocolManager] App disconnected - local players may resume")
        # Reset protocol detection flags
        self.is_millennium = False
        self.is_pegasus = False
        self.is_chessnut = False
        self.client_type = self.CLIENT_UNKNOWN
        
        # Recreate emulators for next connection
        self._millennium = Millennium(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        self._pegasus = Pegasus(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        self._chessnut = Chessnut(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        
        # Request move from current player
        self._request_current_player_move()
    
    def cleanup(self):
        """Clean up resources including players, assistants, and game manager."""
        log.info("[ProtocolManager] Starting cleanup...")
        
        # Stop players
        log.info("[ProtocolManager] Stopping players...")
        if self._player_manager:
            try:
                self._player_manager.stop()
                log.info("[ProtocolManager] Players stopped")
            except Exception as e:
                log.error(f"[ProtocolManager] Error stopping players: {e}", exc_info=True)
        else:
            log.info("[ProtocolManager] No player manager to stop")
        
        # Stop assistant manager if active
        log.info("[ProtocolManager] Stopping assistant manager...")
        if self._assistant_manager:
            try:
                self._assistant_manager.stop()
                log.info("[ProtocolManager] Assistant manager stopped")
            except Exception as e:
                log.error(f"[ProtocolManager] Error stopping assistant manager: {e}", exc_info=True)
            self._assistant_manager = None
        else:
            log.info("[ProtocolManager] No assistant manager to stop")
        
        # Unsubscribe from game manager (stops game thread)
        log.info("[ProtocolManager] Unsubscribing from game manager...")
        if self.game_manager:
            try:
                self.game_manager.unsubscribe_game()
                log.info("[ProtocolManager] Unsubscribed from game manager")
            except Exception as e:
                log.error(f"[ProtocolManager] Error unsubscribing from game manager: {e}", exc_info=True)
        else:
            log.info("[ProtocolManager] No game manager to unsubscribe from")
        
        log.info("[ProtocolManager] Cleanup complete")
