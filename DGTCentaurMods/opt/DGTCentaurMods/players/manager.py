# Player Manager
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Manages both players in a chess game. Each game has a white player
# and a black player, and this manager coordinates between them.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from typing import Optional, Callable

import chess

from DGTCentaurMods.board.logging import log
from .base import Player, PlayerType


class PlayerManager:
    """Manages both players in a chess game.
    
    Each game has two players (White and Black). The PlayerManager:
    - Holds references to both players
    - Routes piece events to the current player
    - Routes move requests to the current player
    - Notifies both players of moves made
    - Manages player lifecycle (start/stop)
    
    All players receive piece events and submit moves via callback.
    The difference is how they process events:
    - Human: Forms move from lift/place, submits any move
    - Engine/Lichess: Has pending move, only submits if events match
    
    Example:
        # Setup
        white_player = HumanPlayer()
        black_player = create_engine_player(chess.BLACK, "stockfish_pi")
        
        manager = PlayerManager(white_player, black_player)
        manager.set_move_callback(on_move)
        manager.set_pending_move_callback(on_pending_move)  # For LED display
        manager.start()
        
        # On each turn
        manager.request_move(board)
        
        # Route piece events
        manager.on_piece_event("lift", square, board)
        manager.on_piece_event("place", square, board)
        
        # When a move is made
        manager.on_move_made(move, board)
    """
    
    def __init__(
        self,
        white_player: Player,
        black_player: Player,
        move_callback: Optional[Callable[[chess.Move], bool]] = None,
        pending_move_callback: Optional[Callable[[chess.Move], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        error_callback: Optional[Callable[[str], None]] = None,
        ready_callback: Optional[Callable[[], None]] = None,
    ):
        """Initialize the player manager.
        
        Args:
            white_player: The player for White.
            black_player: The player for Black.
            move_callback: Called when any player submits a move.
            pending_move_callback: Called when a player has a pending move (for LEDs).
            status_callback: Called with status messages.
            error_callback: Called when a player reports an error (e.g., place without lift).
            ready_callback: Called when all players are ready.
        """
        self._white_player = white_player
        self._black_player = black_player
        self._move_callback = move_callback
        self._pending_move_callback = pending_move_callback
        self._status_callback = status_callback
        self._error_callback = error_callback
        self._ready_callback = ready_callback
        self._ready_fired = False  # Only fire once
        
        # Set colors
        self._white_player.color = chess.WHITE
        self._black_player.color = chess.BLACK
        
        # Wire callbacks
        self._wire_callbacks()
        
        log.info(f"[PlayerManager] Created with White={white_player.name} ({white_player.player_type.name}), "
                 f"Black={black_player.name} ({black_player.player_type.name})")
    
    def _wire_callbacks(self) -> None:
        """Wire callbacks to players."""
        # Move callback - all players submit moves via this
        if self._move_callback:
            self._white_player.set_move_callback(self._move_callback)
            self._black_player.set_move_callback(self._move_callback)
        
        # Pending move callback - for LED display
        if self._pending_move_callback:
            self._white_player.set_pending_move_callback(self._pending_move_callback)
            self._black_player.set_pending_move_callback(self._pending_move_callback)
        
        # Status callback
        if self._status_callback:
            self._white_player.set_status_callback(self._status_callback)
            self._black_player.set_status_callback(self._status_callback)
        
        # Error callback
        if self._error_callback:
            self._white_player.set_error_callback(self._error_callback)
            self._black_player.set_error_callback(self._error_callback)
        
        # Ready callback - fire manager callback when both players ready
        self._white_player.set_ready_callback(self._on_player_ready)
        self._black_player.set_ready_callback(self._on_player_ready)
    
    def _on_player_ready(self) -> None:
        """Handle a player becoming ready.
        
        Fires the manager's ready callback when both players are ready.
        Only fires once.
        """
        if self._ready_fired:
            return
        
        if self.is_ready:
            self._ready_fired = True
            log.info("[PlayerManager] All players ready")
            if self._ready_callback:
                self._ready_callback()
    
    # =========================================================================
    # Callback Setters
    # =========================================================================
    
    def set_move_callback(self, callback: Callable[[chess.Move], bool]) -> None:
        """Set callback for when a player submits a move.
        
        All players submit moves via this callback after piece events.
        
        Args:
            callback: Function(move) -> bool. Returns True if accepted, False if rejected.
        """
        self._move_callback = callback
        self._white_player.set_move_callback(callback)
        self._black_player.set_move_callback(callback)
    
    def set_pending_move_callback(self, callback: Callable[[chess.Move], None]) -> None:
        """Set callback for when a player has a pending move to display.
        
        Used for LED display. Called when engine computes or server sends.
        
        Args:
            callback: Function(move) called for LED display.
        """
        self._pending_move_callback = callback
        self._white_player.set_pending_move_callback(callback)
        self._black_player.set_pending_move_callback(callback)
    
    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for player status messages.
        
        Args:
            callback: Function(message) for status updates.
        """
        self._status_callback = callback
        self._white_player.set_status_callback(callback)
        self._black_player.set_status_callback(callback)
    
    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for player error conditions.
        
        Called when a player detects an error that requires correction mode,
        such as place-without-lift (extra piece on board).
        
        Args:
            callback: Function(error_type) for error conditions.
        """
        self._error_callback = callback
        self._white_player.set_error_callback(callback)
        self._black_player.set_error_callback(callback)
    
    # =========================================================================
    # Lifecycle Methods
    # =========================================================================
    
    def start(self) -> bool:
        """Start both players.
        
        Returns:
            True if both players started successfully.
        """
        log.info("[PlayerManager] Starting players")
        
        white_ok = self._white_player.start()
        black_ok = self._black_player.start()
        
        if not white_ok:
            log.error("[PlayerManager] White player failed to start")
        if not black_ok:
            log.error("[PlayerManager] Black player failed to start")
        
        return white_ok and black_ok
    
    def stop(self) -> None:
        """Stop both players and release resources."""
        log.info("[PlayerManager] Stopping players")
        self._white_player.stop()
        self._black_player.stop()
    
    def on_new_game(self) -> None:
        """Notify both players of new game."""
        self._white_player.on_new_game()
        self._black_player.on_new_game()
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notify both players of takeback.
        
        Args:
            board: Board position after takeback.
        """
        self._white_player.on_takeback(board)
        self._black_player.on_takeback(board)
    
    # =========================================================================
    # Game Flow Methods
    # =========================================================================
    
    def get_player(self, color: chess.Color) -> Player:
        """Get the player for a specific color.
        
        Args:
            color: chess.WHITE or chess.BLACK
            
        Returns:
            The player for that color.
        """
        return self._white_player if color == chess.WHITE else self._black_player
    
    def get_current_player(self, board: chess.Board) -> Player:
        """Get the player whose turn it is.
        
        Args:
            board: Current board position.
            
        Returns:
            The player to move.
        """
        return self.get_player(board.turn)
    
    def get_current_pending_move(self, board: chess.Board) -> Optional[chess.Move]:
        """Get the pending move from the current player, if any.
        
        For engine/Lichess players, this returns the computed move waiting
        to be executed on the physical board. For humans, returns None.
        
        Args:
            board: Current board position.
            
        Returns:
            The pending move, or None if no move is pending.
        """
        return self.get_current_player(board).pending_move
    
    def request_move(self, board: chess.Board) -> None:
        """Request a move from the current player.
        
        Notifies the current player it's their turn. They should prepare
        to receive piece events and eventually submit a move.
        
        The player's base class handles queuing if not yet ready.
        If the player is already thinking, this is a no-op.
        
        Args:
            board: Current board position.
        """
        player = self.get_current_player(board)
        
        # Skip if player is already thinking (avoids redundant calls)
        if player.is_thinking:
            log.debug(f"[PlayerManager] {player.name} already thinking, skipping request")
            return
        
        log.debug(f"[PlayerManager] Requesting move from {player.name}")
        player.request_move(board)
    
    def on_piece_event(self, event_type: str, square: int, board: chess.Board) -> None:
        """Route a piece event to the current player.
        
        Called when a piece is lifted or placed on the physical board.
        The current player processes the event and may submit a move.
        
        Args:
            event_type: "lift" or "place"
            square: The square index (0-63)
            board: Current board position
        """
        player = self.get_current_player(board)
        player.on_piece_event(event_type, square, board)
    
    def on_move_made(self, move: chess.Move, board: chess.Board) -> None:
        """Notify both players that a move was made.
        
        Args:
            move: The move that was made.
            board: Board position after the move.
        """
        self._white_player.on_move_made(move, board)
        self._black_player.on_move_made(move, board)
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def white_player(self) -> Player:
        """The White player."""
        return self._white_player
    
    @property
    def black_player(self) -> Player:
        """The Black player."""
        return self._black_player
    
    @property
    def is_two_human(self) -> bool:
        """Check if both players are human (2-player mode)."""
        return (self._white_player.player_type == PlayerType.HUMAN and 
                self._black_player.player_type == PlayerType.HUMAN)
    
    @property
    def has_engine(self) -> bool:
        """Check if either player is an engine."""
        return (self._white_player.player_type == PlayerType.ENGINE or 
                self._black_player.player_type == PlayerType.ENGINE)
    
    @property
    def has_lichess(self) -> bool:
        """Check if either player is Lichess."""
        return (self._white_player.player_type == PlayerType.LICHESS or 
                self._black_player.player_type == PlayerType.LICHESS)
    
    @property
    def is_ready(self) -> bool:
        """Check if both players are ready."""
        return self._white_player.is_ready and self._black_player.is_ready
    
    @property
    def supports_takeback(self) -> bool:
        """Check if both players support takeback."""
        return (self._white_player.supports_takeback() and 
                self._black_player.supports_takeback())
    
    def get_info(self) -> dict:
        """Get information about both players."""
        return {
            'white': self._white_player.get_info(),
            'black': self._black_player.get_info(),
            'is_two_human': self.is_two_human,
            'has_engine': self.has_engine,
            'has_lichess': self.has_lichess,
        }
