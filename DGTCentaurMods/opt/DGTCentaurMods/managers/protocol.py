# Protocol Manager
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# This project started as a fork of DGTCentaur Mods by EdNekebno
# ( https://github.com/EdNekebno/DGTCentaur )
#
# Manages player integrations, assistant management, and game callbacks.
# Protocol emulation (Millennium, Pegasus, Chessnut) is now handled by
# RemoteController in the controllers/ module.
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

from DGTCentaurMods.managers.game import GameManager
log.debug(f"[protocol import] game: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

# Import Player and Assistant managers
from DGTCentaurMods.players import PlayerManager
from DGTCentaurMods.managers.assistant import AssistantManager
log.debug(f"[protocol import] players/assistant managers: {(_t.time() - _s)*1000:.0f}ms"); _s = _t.time()

import chess
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
        
        # Note: Emulators are now created by RemoteController, not ProtocolManager.
        # These fields are kept for backward compatibility but are no longer used.
        self._millennium = None
        self._pegasus = None
        self._chessnut = None
        
        # Note: GameManager subscription is now handled by LocalController.start()
        # ProtocolManager no longer subscribes directly.
        
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
        """Legacy method - data routing now handled by ControllerManager.
        
        This method is no longer called. Protocol data is routed through
        ControllerManager.receive_bluetooth_data() -> RemoteController.receive_data().
        
        Args:
            byte_value: Raw byte value from wire
            
        Returns:
            False (no longer processes data)
        """
        log.warning("[ProtocolManager] receive_data called but is now handled by ControllerManager")
        return False

    def reset_parser(self):
        """Legacy method - emulator state now managed by RemoteController."""
        log.debug("[ProtocolManager] reset_parser called but emulators are now in RemoteController")

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
        """Legacy method for direct player move handling.
        
        Note: This method is no longer used. Player moves are now routed through
        GameManager._on_player_move which is wired by game_manager.set_player_manager().
        
        This method called computer_move() which was incorrect for human moves
        (showed LEDs and set forced move flag instead of executing the move).
        
        Args:
            move: The player's move.
        """
        log.warning(f"[ProtocolManager] Legacy _on_player_move called for {move.uci()} - this should not happen")
        self.game_manager.computer_move(move.uci(), forced=True)
    
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
    
    # =========================================================================
    # App Connection Management
    # =========================================================================
    
    def is_app_connected(self) -> bool:
        """Check if any chess app protocol has been detected.
        
        Note: When ControllerManager is used, controller switching is managed
        by ControllerManager, not by checking this method.
        
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
        """Called when app disconnects - resume local players.
        
        Emulator recreation is now handled by ControllerManager/RemoteController.
        """
        log.info("[ProtocolManager] App disconnected - local players may resume")
        # Reset protocol detection flags
        self.is_millennium = False
        self.is_pegasus = False
        self.is_chessnut = False
        self.client_type = self.CLIENT_UNKNOWN
        
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
