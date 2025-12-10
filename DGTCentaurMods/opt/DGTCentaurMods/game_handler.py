# Game Handler
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.emulators.millennium import Millennium
from DGTCentaurMods.emulators.pegasus import Pegasus
from DGTCentaurMods.emulators.chessnut import Chessnut
from DGTCentaurMods.game_manager import GameManager, EVENT_NEW_GAME, EVENT_WHITE_TURN, EVENT_BLACK_TURN

import chess
import chess.engine
import pathlib
import os
import configparser


class GameHandler:
    """Game handler that supports multiple protocols (Millennium, Pegasus, Chessnut).
    
    This class can operate in two modes:
    1. Known client type (BLE): Only creates the specific emulator for that protocol
    2. Unknown client type (RFCOMM): Creates all RFCOMM-capable emulators and auto-detects
    
    In relay mode (compare_mode=True), emulator responses are buffered for comparison
    with shadow host responses instead of being sent directly to the client.
    """
    
    # Client type constants
    CLIENT_UNKNOWN = "unknown"
    CLIENT_MILLENNIUM = "millennium"
    CLIENT_PEGASUS = "pegasus"
    CLIENT_CHESSNUT = "chessnut"
    
    def __init__(self, sendMessage_callback=None, client_type=None, compare_mode=False,
                 standalone_engine_name=None, player_color=chess.WHITE, engine_elo="Default",
                 display_update_callback=None):
        """Initialize the GameHandler.
        
        Args:
            sendMessage_callback: Callback function(data) for sending messages to client
            client_type: Hint about client type from BLE service UUID:
                        - CLIENT_MILLENNIUM: Millennium ChessLink
                        - CLIENT_PEGASUS: Nordic UART (Pegasus)
                        - CLIENT_CHESSNUT: Chessnut Air
                        - CLIENT_UNKNOWN or None: Auto-detect from incoming data (RFCOMM)
            compare_mode: If True, buffer emulator responses for comparison with
                         shadow host instead of sending directly. Used in relay mode.
            standalone_engine_name: Name of UCI engine to use when no app connected
                                   (e.g., "stockfish_pi", "maia", "ct800")
            player_color: Which color the human plays (chess.WHITE or chess.BLACK)
            engine_elo: ELO section name from .uci config file (e.g., "1350", "1700", "Default")
            display_update_callback: Callback function(fen) for updating display with position
        """
        self._sendMessage = sendMessage_callback
        self.compare_mode = compare_mode
        self._pending_response = None
        self._display_update_callback = display_update_callback
        self._external_event_callback = None  # Optional callback for game events
        
        # Store the hint but don't trust it - always verify from data
        self._client_type_hint = client_type
        self.client_type = self.CLIENT_UNKNOWN
        
        # Protocol detection flags - only set True after data confirms protocol
        self.is_millennium = False
        self.is_pegasus = False
        self.is_chessnut = False
        
        # UCI standalone engine settings (for standalone play without app)
        self._standalone_engine = None
        self._standalone_engine_name = standalone_engine_name
        self._player_color = player_color
        self._engine_elo = engine_elo
        self._uci_options = {}
        
        # Game manager shared by all emulators
        self.game_manager = GameManager()
        
        # Emulator instances - always create all emulators for auto-detection
        # The hint from BLE characteristic is unreliable as apps may connect to any service
        self._millennium = None
        self._pegasus = None
        self._chessnut = None
        
        # Always create all emulators for auto-detection from actual data
        # The client_type hint from BLE service UUID is unreliable
        log.info(f"[GameHandler] Creating emulators for auto-detection (hint: {client_type or 'none'})")
        
        # Create Millennium emulator
        self._millennium = Millennium(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        log.info("[GameHandler] Created Millennium emulator")
        
        # Create Pegasus emulator
        self._pegasus = Pegasus(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        log.info("[GameHandler] Created Pegasus emulator")
        
        # Create Chessnut emulator
        self._chessnut = Chessnut(
            sendMessage_callback=self._handle_emulator_response,
            manager=self.game_manager
        )
        log.info("[GameHandler] Created Chessnut emulator")
        
        # Initialize standalone UCI engine if configured
        if standalone_engine_name:
            self._initialize_standalone_engine()
            # If player is black, engine needs to move first after game starts
            # This will be triggered when we receive the first EVENT_WHITE_TURN
        
        self.subscribe_manager()
    
    def _handle_emulator_response(self, data):
        """Handle response generated by an emulator.
        
        In compare_mode, buffers the response for later comparison with shadow host.
        Otherwise, sends directly to the client.
        
        Args:
            data: Response data bytes from emulator
        """
        if self.compare_mode:
            self._pending_response = bytes(data) if data else None
            log.debug(f"[GameHandler] Emulator response buffered ({len(data) if data else 0} bytes)")
        else:
            if self._sendMessage:
                self._sendMessage(data)
    
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
            log.debug("[GameHandler] No emulator response to compare (emulator may not have generated one)")
            return (None, None)
        
        shadow_bytes = bytes(shadow_response) if shadow_response else b''
        match = emulator_response == shadow_bytes
        
        if not match:
            log.warning("[GameHandler] Response MISMATCH between emulator and shadow host:")
            log.warning(f"  Shadow host: {shadow_bytes.hex() if shadow_bytes else '(empty)'}")
            log.warning(f"  Emulator:    {emulator_response.hex() if emulator_response else '(empty)'}")
        else:
            log.debug(f"[GameHandler] Response match: {shadow_bytes.hex()}")
        
        return (match, emulator_response)
    
    def _manager_event_callback(self, event, piece_event=None, field=None, time_in_seconds=None):
        """Handle game events from the manager.
        
        Routes events to the active emulator based on detected protocol.
        Before protocol is confirmed, forwards to ALL emulators so that
        whichever one is active will respond correctly.
        
        Args:
            event: Event constant (EVENT_NEW_GAME, EVENT_WHITE_TURN, etc.)
            piece_event: Piece event type
            field: Chess field index
            time_in_seconds: Time since game start
        """
        try:
            log.debug(f"[GameHandler] _manager_event_callback: {event} piece_event={piece_event}, field={field}")
            log.debug(f"[GameHandler] Flags: is_millennium={self.is_millennium}, is_pegasus={self.is_pegasus}, is_chessnut={self.is_chessnut}")
            log.debug(f"[GameHandler] Emulators: _millennium={self._millennium is not None}, _pegasus={self._pegasus is not None}, _chessnut={self._chessnut is not None}")
            
            # If protocol is confirmed, only forward to the active emulator
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_event'):
                log.debug("[GameHandler] Routing event to Millennium")
                self._millennium.handle_manager_event(event, piece_event, field, time_in_seconds)
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_event'):
                log.debug("[GameHandler] Routing event to Pegasus")
                self._pegasus.handle_manager_event(event, piece_event, field, time_in_seconds)
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_event'):
                log.debug("[GameHandler] Routing event to Chessnut")
                self._chessnut.handle_manager_event(event, piece_event, field, time_in_seconds)
            else:
                # Protocol not yet confirmed - forward to ALL emulators
                # Each emulator will only act if it has reporting enabled
                log.debug("[GameHandler] Protocol not confirmed, forwarding event to all emulators")
                if self._millennium and hasattr(self._millennium, 'handle_manager_event'):
                    self._millennium.handle_manager_event(event, piece_event, field, time_in_seconds)
                if self._pegasus and hasattr(self._pegasus, 'handle_manager_event'):
                    self._pegasus.handle_manager_event(event, piece_event, field, time_in_seconds)
                if self._chessnut and hasattr(self._chessnut, 'handle_manager_event'):
                    self._chessnut.handle_manager_event(event, piece_event, field, time_in_seconds)
                
                # Handle standalone engine events (no app connected)
                if event == EVENT_NEW_GAME:
                    # Reset engine state on new game
                    self._handle_new_game()
                elif event == EVENT_WHITE_TURN or event == EVENT_BLACK_TURN:
                    # Turn events are triggered AFTER the player's move is confirmed
                    self._check_standalone_engine_turn()
            
            # Notify external event callback
            if self._external_event_callback:
                try:
                    self._external_event_callback(event)
                except Exception as e:
                    log.debug(f"[GameHandler] Error in external event callback: {e}")
            
            # Update display with current position
            self._update_display()
        except Exception as e:
            log.error(f"[GameHandler] Error in _manager_event_callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_move_callback(self, move):
        """Handle moves from the manager.
        
        Before protocol is confirmed, forwards to ALL emulators.
        Note: Standalone engine is triggered by turn events (EVENT_WHITE_TURN, EVENT_BLACK_TURN)
        which occur AFTER the move is confirmed, not by this callback.
        
        Args:
            move: Chess move object
        """
        try:
            log.debug(f"[GameHandler] _manager_move_callback: {move}")
            
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_move'):
                self._millennium.handle_manager_move(move)
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_move'):
                self._pegasus.handle_manager_move(move)
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_move'):
                self._chessnut.handle_manager_move(move)
            else:
                # Protocol not yet confirmed - forward to ALL emulators
                log.debug("[GameHandler] Protocol not confirmed, forwarding move to all emulators")
                if self._millennium and hasattr(self._millennium, 'handle_manager_move'):
                    self._millennium.handle_manager_move(move)
                if self._pegasus and hasattr(self._pegasus, 'handle_manager_move'):
                    self._pegasus.handle_manager_move(move)
                if self._chessnut and hasattr(self._chessnut, 'handle_manager_move'):
                    self._chessnut.handle_manager_move(move)
                # Note: Standalone engine is triggered by turn events, not move events
                # Turn events happen AFTER the player's move is acknowledged with LEDs
            
            # Update display with current position
            self._update_display()
        except Exception as e:
            log.error(f"[GameHandler] Error in _manager_move_callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_key_callback(self, key):
        """Handle key presses forwarded from GameManager.
        
        Forwards key events to active emulators that need to know about them.
        
        Args:
            key: Key that was pressed (board.Key enum value)
        """
        try:
            log.debug(f"[GameHandler] _manager_key_callback: {key}")
            
            # Forward to active emulator
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_key'):
                self._millennium.handle_manager_key(key)
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_key'):
                self._pegasus.handle_manager_key(key)
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_key'):
                self._chessnut.handle_manager_key(key)
        except Exception as e:
            log.error(f"[GameHandler] Error in _manager_key_callback: {e}")
            import traceback
            traceback.print_exc()
    
    def _manager_takeback_callback(self):
        """Handle takeback requests from the manager."""
        try:
            log.info("[GameHandler] _manager_takeback_callback")
            
            if self.is_millennium and self._millennium and hasattr(self._millennium, 'handle_manager_takeback'):
                self._millennium.handle_manager_takeback()
            elif self.is_pegasus and self._pegasus and hasattr(self._pegasus, 'handle_manager_takeback'):
                self._pegasus.handle_manager_takeback()
            elif self.is_chessnut and self._chessnut and hasattr(self._chessnut, 'handle_manager_takeback'):
                self._chessnut.handle_manager_takeback()
        except Exception as e:
            log.error(f"[GameHandler] Error in _manager_takeback_callback: {e}")
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
        # Build priority order - hinted protocol first, then others
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
            # No hint - default order
            emulators_to_try = [
                (self._millennium, "Millennium", self.CLIENT_MILLENNIUM),
                (self._pegasus, "Pegasus", self.CLIENT_PEGASUS),
                (self._chessnut, "Chessnut", self.CLIENT_CHESSNUT),
            ]
        
        for emulator, name, client_type in emulators_to_try:
            if emulator and emulator.parse_byte(byte_value):
                hint_match = " (matches hint)" if self._client_type_hint == client_type else ""
                hint_mismatch = f" (hint was {self._client_type_hint})" if self._client_type_hint and self._client_type_hint != client_type else ""
                log.info(f"[GameHandler] {name} protocol detected via auto-detection{hint_match}{hint_mismatch}")
                
                self.client_type = client_type
                
                # Set the appropriate flag and free unused emulators
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
        """Reset the packet parser state for all active emulators.
        
        Clears any accumulated buffer and resets parser to initial state.
        Useful when starting a new communication session or recovering from errors.
        """
        if self._millennium:
            self._millennium.reset_parser()
        if self._pegasus:
            self._pegasus.reset()
        if self._chessnut:
            self._chessnut.reset()

    def _update_display(self):
        """Update the e-paper display with the current board position.
        
        Calls the display update callback if one was provided during initialization.
        The callback receives the current FEN string from the game manager.
        """
        if self._display_update_callback and self.game_manager:
            try:
                fen = self.game_manager.chess_board.fen()
                self._display_update_callback(fen)
            except Exception as e:
                log.error(f"[GameHandler] Error updating display: {e}")

    def subscribe_manager(self):
        """Subscribe to the game manager with callbacks."""
        try:
            log.info("[GameHandler] Subscribing to game manager")
            self.game_manager.subscribe_game(
                self._manager_event_callback,
                self._manager_move_callback,
                self._manager_key_callback,
                self._manager_takeback_callback
            )
            log.info("[GameHandler] Successfully subscribed to game manager")
        except Exception as e:
            log.error(f"[GameHandler] Failed to subscribe to game manager: {e}")
            import traceback
            traceback.print_exc()
    
    # =========================================================================
    # UCI Standalone Engine Methods
    # =========================================================================
    
    def _initialize_standalone_engine(self):
        """Initialize the UCI standalone engine with ELO settings.
        
        The standalone engine plays when no chess app is connected, allowing
        the board to be used standalone against a chess engine.
        """
        if not self._standalone_engine_name:
            return
        
        base_path = pathlib.Path(__file__).parent
        engine_path = base_path / "engines" / self._standalone_engine_name
        uci_file_path = str(engine_path) + ".uci"
        
        if not engine_path.exists():
            log.error(f"[GameHandler] Standalone engine not found: {engine_path}")
            log.error(f"[GameHandler] Standalone play will not be available")
            return
        
        # Load UCI options from config file
        self._load_uci_options(uci_file_path)
        
        try:
            self._standalone_engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
            log.info(f"[GameHandler] Standalone UCI engine initialized: {self._standalone_engine_name} @ {self._engine_elo}")
            
            # Apply UCI options (ELO settings)
            if self._uci_options:
                log.info(f"[GameHandler] Configuring engine with options: {self._uci_options}")
                self._standalone_engine.configure(self._uci_options)
                
        except Exception as e:
            log.error(f"[GameHandler] Failed to initialize standalone engine: {e}")
            import traceback
            traceback.print_exc()
            self._standalone_engine = None
    
    def _load_uci_options(self, uci_file_path: str):
        """Load UCI options from configuration file.
        
        Args:
            uci_file_path: Path to the .uci config file (e.g., engines/stockfish_pi.uci)
        """
        if not os.path.exists(uci_file_path):
            log.warning(f"[GameHandler] UCI file not found: {uci_file_path}, using defaults")
            return
        
        config = configparser.ConfigParser()
        config.optionxform = str  # Preserve case for UCI option names
        config.read(uci_file_path)
        
        section = self._engine_elo
        
        if config.has_section(section):
            log.info(f"[GameHandler] Loading UCI options from section: {section}")
            for key, value in config.items(section):
                self._uci_options[key] = value
            
            # Filter out non-UCI metadata fields
            non_uci_fields = ['Description']
            self._uci_options = {
                k: v for k, v in self._uci_options.items()
                if k not in non_uci_fields
            }
            log.info(f"[GameHandler] UCI options: {self._uci_options}")
        else:
            log.warning(f"[GameHandler] Section '{section}' not found in {uci_file_path}")
            if config.has_section("DEFAULT"):
                for key, value in config.items("DEFAULT"):
                    if key != 'Description':
                        self._uci_options[key] = value
    
    def is_app_connected(self) -> bool:
        """Check if any chess app protocol has been detected.
        
        Returns:
            True if a chess app is connected (Millennium, Pegasus, or Chessnut)
        """
        return self.is_millennium or self.is_pegasus or self.is_chessnut
    
    def _handle_new_game(self):
        """Handle new game event for standalone engine.
        
        Resets engine state when a new game starts (board reset to starting position).
        """
        if not self._standalone_engine:
            return
        
        log.info("[GameHandler] New game detected - resetting standalone engine state")
        
        # Send ucinewgame to reset engine's internal state
        try:
            # The chess.engine library handles ucinewgame automatically on new positions
            # but we log this for clarity
            log.info("[GameHandler] Engine state will be reset on next move")
        except Exception as e:
            log.error(f"[GameHandler] Error resetting engine state: {e}")
    
    def _check_standalone_engine_turn(self):
        """If no app connected and it's engine's turn, play a move.
        
        This enables standalone play against a chess engine when no app is connected.
        The engine move is displayed via LEDs and the player must execute it on the board.
        """
        if self.is_app_connected():
            return  # App is connected, don't use standalone engine
        
        if not self._standalone_engine:
            return  # No standalone engine configured
        
        # Get current board state from manager
        chess_board = self.game_manager.chess_board
        
        # Check if it's the engine's turn
        engine_color = chess.BLACK if self._player_color == chess.WHITE else chess.WHITE
        if chess_board.turn != engine_color:
            return  # Not engine's turn
        
        # Check if game is over
        if chess_board.is_game_over():
            return
        
        log.info(f"[GameHandler] Standalone engine ({self._standalone_engine_name} @ {self._engine_elo}) thinking...")
        
        try:
            # Re-apply UCI options before each move
            if self._uci_options:
                self._standalone_engine.configure(self._uci_options)
            
            # Get engine move with time limit
            result = self._standalone_engine.play(chess_board, chess.engine.Limit(time=5.0))
            move = result.move
            
            if move:
                log.info(f"[GameHandler] Standalone engine move: {move.uci()}")
                # Use manager.computer_move to set up the forced move with LEDs
                # This lights up the from/to squares and waits for player to execute the move
                self.game_manager.computer_move(move.uci(), forced=True)
                log.info(f"[GameHandler] Waiting for player to execute move {move.uci()} on board")
        except Exception as e:
            log.error(f"[GameHandler] Error getting standalone engine move: {e}")
            import traceback
            traceback.print_exc()
    
    def on_app_connected(self):
        """Called when an app connects - pause standalone engine.
        
        The protocol detection flags will be set by receive_data() which will
        naturally stop the standalone engine from playing.
        """
        log.info("[GameHandler] App connected - standalone engine paused")
    
    def on_app_disconnected(self):
        """Called when app disconnects - resume standalone engine.
        
        Resets protocol detection flags so the standalone engine can resume playing.
        """
        log.info("[GameHandler] App disconnected - standalone engine may resume")
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
        
        # Check if engine should play now
        self._check_standalone_engine_turn()
    
    def cleanup(self):
        """Clean up resources including UCI engine and game manager.
        
        Properly stops the game manager thread and closes the UCI engine.
        """
        # Unsubscribe from game manager first (stops game thread)
        if self.game_manager:
            try:
                self.game_manager.unsubscribe_game()
                log.info("[GameHandler] Unsubscribed from game manager")
            except Exception as e:
                log.error(f"[GameHandler] Error unsubscribing from game manager: {e}")
        
        # Close standalone engine
        if self._standalone_engine:
            try:
                self._standalone_engine.quit()
                log.info("[GameHandler] Standalone engine closed")
            except Exception as e:
                log.error(f"[GameHandler] Error closing standalone engine: {e}")
            self._standalone_engine = None
