# Player Base Class
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Abstract base class for all players. A player is an entity that makes
# moves in a chess game. Each game has two players (White and Black).
#
# All players receive piece events and submit moves via callback:
# - HumanPlayer: Constructs moves from piece events
# - EnginePlayer: Computes moves, piece events confirm execution
# - LichessPlayer: Receives moves from server, piece events confirm execution
#
# The game validates all submitted moves the same way.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Callable

import chess


class PlayerState(Enum):
    """State machine states for player lifecycle.
    
    All players follow this state machine:
    - UNINITIALIZED: Not yet started
    - INITIALIZING: Loading resources, connecting, etc.
    - READY: Ready to play, waiting for turn
    - THINKING: Computing/waiting for a move
    - ERROR: Error state, cannot continue
    - STOPPED: Cleanly stopped
    """
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    READY = auto()
    THINKING = auto()
    ERROR = auto()
    STOPPED = auto()


class PlayerType(Enum):
    """Type of player - determines how moves are sourced.
    
    HUMAN: Moves come from physical board interactions.
           The game waits for the human to move pieces.
    
    ENGINE: Moves come from a UCI chess engine.
            The engine computes moves, human executes them on board.
    
    LICHESS: Moves come from the Lichess server.
             For online games, the server determines the move.
    
    REMOTE: Moves come from a remote human (network play).
            Another human provides moves, local human executes them.
    """
    HUMAN = auto()
    ENGINE = auto()
    LICHESS = auto()
    REMOTE = auto()


@dataclass
class PlayerConfig:
    """Base configuration for players.
    
    Subclasses should extend this with player-specific settings.
    
    Attributes:
        name: Human-readable name for display/logging.
        color: The color this player plays (WHITE or BLACK).
               Set when the player is assigned to a game.
    """
    name: str = "Player"
    color: Optional[chess.Color] = None


class Player(ABC):
    """Abstract base class for chess players.
    
    A player is an entity that makes moves in a chess game. The game
    has two players (White and Black), and on each turn the appropriate
    player provides a move.
    
    All players submit moves via the move_callback. The difference is
    how they determine what move to submit:
    
    - HumanPlayer: Constructs a move from piece events (lift A, place B)
    - EnginePlayer: Computes a move, then validates piece events match
    - LichessPlayer: Receives a move from server, validates piece events match
    
    Key Methods:
    - request_move(): Called when it's this player's turn
    - on_piece_event(): Called when a piece is lifted/placed on the board
    - on_move_made(): Notify that a move was made (by either player)
    - can_resign(): Whether this player can be resigned via the board
    
    Move Flow:
    1. request_move() is called when it's this player's turn
    2. on_piece_event() is called for each lift/place event
    3. Player determines a move and calls move_callback
    4. Game validates the move and executes it (or enters correction mode)
    
    Thread Safety:
    Players may be called from multiple threads. Implementations should
    ensure thread safety, especially for request_move() which may spawn
    background threads.
    """
    
    def __init__(self, config: Optional[PlayerConfig] = None):
        """Initialize the player.
        
        Args:
            config: Configuration for this player. If None, uses defaults.
        """
        self._config = config or PlayerConfig()
        self._state = PlayerState.UNINITIALIZED
        self._error_message: Optional[str] = None
        self._color: Optional[chess.Color] = config.color if config else None
        
        # Callbacks set by the game coordinator
        self._move_callback: Optional[Callable[[chess.Move], bool]] = None
        self._pending_move_callback: Optional[Callable[[chess.Move], None]] = None
        self._status_callback: Optional[Callable[[str], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None
        
        # Track lifted square for move formation
        self._lifted_square: Optional[int] = None
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def name(self) -> str:
        """Human-readable name of this player."""
        return self._config.name
    
    @property
    def color(self) -> Optional[chess.Color]:
        """The color this player plays (WHITE or BLACK)."""
        return self._color
    
    @color.setter
    def color(self, value: chess.Color) -> None:
        """Set the color this player plays."""
        self._color = value
    
    @property
    def state(self) -> PlayerState:
        """Current state of the player."""
        return self._state
    
    @property
    def is_ready(self) -> bool:
        """Whether the player is ready to play."""
        return self._state == PlayerState.READY
    
    @property
    def is_thinking(self) -> bool:
        """Whether the player is currently computing/waiting for a move."""
        return self._state == PlayerState.THINKING
    
    @property
    def error_message(self) -> Optional[str]:
        """Error message if state is ERROR, None otherwise."""
        return self._error_message
    
    @property
    @abstractmethod
    def player_type(self) -> PlayerType:
        """The type of this player (HUMAN, ENGINE, etc.)."""
        pass
    
    def can_resign(self) -> bool:
        """Whether this player can resign via the board interface.
        
        Returns True if the player at the physical board can choose to
        resign on behalf of this player. Default is True.
        
        Override in subclasses for players that cannot be resigned
        (e.g., remote players in some online modes).
        """
        return True
    
    def supports_late_castling(self) -> bool:
        """Whether this player supports late castling.
        
        Late castling is when a player moves the rook first (e.g., h1f1),
        then moves the king to the castling square (e.g., e1g1). The game
        undoes the rook move and executes castling instead.
        
        This is a convenience feature for beginners on physical boards.
        Not supported for online play (e.g., Lichess) where moves cannot
        be undone after submission.
        
        Default is True for local players (human, engine).
        Override to return False for remote/online players.
        """
        return True
    
    # =========================================================================
    # Callback Management
    # =========================================================================
    
    def set_move_callback(self, callback: Callable[[chess.Move], bool]) -> None:
        """Set callback for when player submits a move.

        All players use this callback to submit moves to the game.
        The callback is invoked when piece events form a move.

        Args:
            callback: Function(move) -> bool. Returns True if move was
                     accepted (valid), False if rejected (invalid).
                     Players like Lichess need the return value to know
                     if the move should be sent to the server.
        """
        self._move_callback = callback
    
    def set_pending_move_callback(self, callback: Callable[[chess.Move], None]) -> None:
        """Set callback for when player has a pending move to display.
        
        Called when the player has determined what move should be made,
        before piece events confirm execution. Used for LED display.
        
        - Human: Not used (no pending move - they're deciding)
        - Engine: Called when engine finishes computing
        - Lichess: Called when server sends a move
        
        Args:
            callback: Function to call with the pending move (for LEDs).
        """
        self._pending_move_callback = callback
    
    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for status updates.
        
        Used to display status messages during initialization,
        connection, engine thinking, etc.
        
        Args:
            callback: Function to call with status text.
        """
        self._status_callback = callback
    
    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for error conditions that require correction mode.
        
        Called when the player detects an error condition that the game
        should handle, such as:
        - Place event without corresponding lift (extra piece on board)
        - Non-matching piece events for engine/Lichess moves
        
        Args:
            callback: Function to call with error type string.
                     Error types: "place_without_lift", "move_mismatch"
        """
        self._error_callback = callback
    
    def _report_error(self, error_type: str) -> None:
        """Report an error condition via the callback if set.
        
        Args:
            error_type: Type of error (e.g., "place_without_lift").
        """
        if self._error_callback:
            self._error_callback(error_type)
    
    # =========================================================================
    # State Management (Protected)
    # =========================================================================
    
    def _set_state(self, state: PlayerState, error: Optional[str] = None) -> None:
        """Update the player state.
        
        Args:
            state: New state.
            error: Error message if state is ERROR.
        """
        self._state = state
        if state == PlayerState.ERROR:
            self._error_message = error
        else:
            self._error_message = None
    
    def _report_status(self, message: str) -> None:
        """Report a status message via the callback if set.
        
        Args:
            message: Status message to report.
        """
        if self._status_callback:
            self._status_callback(message)
    
    # =========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # =========================================================================
    
    @abstractmethod
    def start(self) -> bool:
        """Initialize and start the player.
        
        Performs any async initialization: loading engine, connecting
        to online service, etc.
        
        Should set state to READY on success, ERROR on failure.
        
        Returns:
            True if started successfully, False on error.
        """
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the player and release resources.
        
        Clean shutdown: close connections, stop threads, release
        engine processes, etc.
        
        Should set state to STOPPED.
        """
        pass
    
    @abstractmethod
    def request_move(self, board: chess.Board) -> None:
        """Request the player to provide a move.
        
        Called when it's this player's turn. The player should prepare
        to receive piece events and eventually submit a move via callback.
        
        - Human: May show "your turn" indicator, waits for piece events
        - Engine: Starts computing, will submit move when ready
        - Lichess: Waits for server, will submit move when received
        
        Args:
            board: Current chess position.
        """
        pass
    
    def on_piece_event(self, event_type: str, square: int, board: chess.Board) -> None:
        """Handle a piece event from the physical board.

        Called when a piece is lifted or placed on the board.
        Forms a move from lift/place sequence and submits via callback.
        
        Error cases (call error_callback):
        - Place without lift (extra piece on board)
        - Place on same square as lift (piece put back)
        
        Success cases (call move_callback):
        - Lift followed by place on different square
        
        Subclasses can override for additional behavior (e.g., engine
        validating the move matches its computed move).

        Args:
            event_type: "lift" or "place"
            square: The square index (0-63) where the event occurred
            board: Current chess position (before the move)
        """
        if event_type == "lift":
            self._lifted_square = square
        
        elif event_type == "place":
            if self._lifted_square is None:
                # Place without lift - error
                self._report_error("place_without_lift")
                return
            
            from_sq = self._lifted_square
            self._lifted_square = None
            
            if square == from_sq:
                # Piece placed back on same square - error (not a move)
                self._report_error("piece_returned")
                return
            
            # Valid lift/place sequence - form move and submit
            move = chess.Move(from_sq, square)
            if self._move_callback:
                self._move_callback(move)
    
    @abstractmethod
    def on_move_made(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that a move was made on the board.
        
        Called after any move is made (by either player).
        Players can use this to track game state.
        
        Args:
            move: The move that was made.
            board: Board state after the move.
        """
        pass
    
    @abstractmethod
    def on_new_game(self) -> None:
        """Notification that a new game is starting.
        
        Called when the board is reset to starting position.
        Players should reset internal state.
        """
        pass
    
    # =========================================================================
    # Optional Methods - May be overridden by subclasses
    # =========================================================================
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred.
        
        Called when a move is taken back. Not all players support
        takeback. Default implementation does nothing.
        
        Args:
            board: Board state after the takeback.
        """
        pass
    
    def on_resign(self, color: chess.Color) -> None:
        """Notification that a player resigned.
        
        Args:
            color: The color that resigned.
        """
        pass
    
    def on_draw_offer(self) -> None:
        """Notification that a draw was offered.
        
        For online players, this sends the draw offer. Default
        implementation does nothing.
        """
        pass
    
    def supports_takeback(self) -> bool:
        """Whether this player supports takeback.
        
        Returns:
            True if takeback is supported, False otherwise.
        """
        return True
    
    def get_info(self) -> dict:
        """Get information about this player for display.
        
        Returns:
            Dictionary with player info. Keys may include:
            - name: Player name
            - color: WHITE or BLACK
            - type: Player type (human, engine, etc.)
            - state: Current player state
        """
        return {
            'name': self.name,
            'color': 'white' if self._color == chess.WHITE else 'black' if self._color == chess.BLACK else None,
            'type': self.player_type.name,
            'state': self._state.name,
        }
