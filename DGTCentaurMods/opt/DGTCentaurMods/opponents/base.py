# Opponent Base Class
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Abstract base class for all opponents. An opponent is something that
# plays against the user, providing moves in response to the game state.
#
# Designed to be extendable by users who want to implement custom opponents.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, Any
import chess


class OpponentState(Enum):
    """State machine states for opponent lifecycle.
    
    All opponents follow this state machine:
    - UNINITIALIZED: Not yet started
    - INITIALIZING: Loading resources, connecting, etc.
    - READY: Ready to play but not currently thinking
    - THINKING: Computing a move
    - ERROR: Error state, cannot continue
    - STOPPED: Cleanly stopped
    """
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    READY = auto()
    THINKING = auto()
    ERROR = auto()
    STOPPED = auto()


@dataclass
class OpponentConfig:
    """Base configuration for opponents.
    
    Subclasses should extend this with opponent-specific settings.
    
    Note: Opponent color is not stored in config. The caller (game coordinator)
    tracks player color and calls get_move() when board.turn != player_color.
    The opponent computes a move for board.turn.
    
    Attributes:
        name: Human-readable name for display/logging.
        time_limit_seconds: Maximum time for computing a move.
    """
    name: str = "Opponent"
    time_limit_seconds: float = 5.0


class Opponent(ABC):
    """Abstract base class for chess opponents.
    
    An opponent is an entity that plays against the user. It receives
    notifications about game state and provides moves when it's the
    opponent's turn.
    
    Subclasses must implement:
    - start(): Initialize the opponent (async setup, connections, etc.)
    - stop(): Clean shutdown
    - get_move(): Compute and return a move for the current position
    - on_player_move(): Notification when player makes a move
    - on_new_game(): Notification when a new game starts
    
    Thread Safety:
    Opponents may be called from multiple threads. Implementations should
    ensure thread safety, especially for get_move() which may run in a
    background thread.
    
    Extension Point:
    Users can create custom opponents by subclassing this class. The
    opponent will be discovered and usable through the normal game flow.
    """
    
    def __init__(self, config: Optional[OpponentConfig] = None):
        """Initialize the opponent.
        
        Args:
            config: Configuration for this opponent. If None, uses defaults.
        """
        self._config = config or OpponentConfig()
        self._state = OpponentState.UNINITIALIZED
        self._error_message: Optional[str] = None
        
        # Callbacks set by the game coordinator
        self._move_callback: Optional[Callable[[chess.Move], None]] = None
        self._status_callback: Optional[Callable[[str], None]] = None
    
    @property
    def name(self) -> str:
        """Human-readable name of this opponent."""
        return self._config.name
    
    @property
    def state(self) -> OpponentState:
        """Current state of the opponent."""
        return self._state
    
    @property
    def is_ready(self) -> bool:
        """Whether the opponent is ready to play."""
        return self._state == OpponentState.READY
    
    @property
    def is_thinking(self) -> bool:
        """Whether the opponent is currently computing a move."""
        return self._state == OpponentState.THINKING
    
    @property
    def error_message(self) -> Optional[str]:
        """Error message if state is ERROR, None otherwise."""
        return self._error_message
    
    def set_move_callback(self, callback: Callable[[chess.Move], None]) -> None:
        """Set callback for when opponent has computed a move.
        
        The callback receives the chess.Move object. This is used for
        asynchronous opponents (like Lichess) that push moves rather
        than returning them synchronously from get_move().
        
        Args:
            callback: Function to call with the opponent's move.
        """
        self._move_callback = callback
    
    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for status updates.
        
        Used to display status messages during initialization,
        connection, seeking opponents, etc.
        
        Args:
            callback: Function to call with status text.
        """
        self._status_callback = callback
    
    def _set_state(self, state: OpponentState, error: Optional[str] = None) -> None:
        """Update the opponent state.
        
        Args:
            state: New state.
            error: Error message if state is ERROR.
        """
        self._state = state
        if state == OpponentState.ERROR:
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
        """Initialize and start the opponent.
        
        Performs any async initialization: loading engine, connecting
        to online service, etc.
        
        Should set state to READY on success, ERROR on failure.
        
        Returns:
            True if started successfully, False on error.
        """
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the opponent and release resources.
        
        Clean shutdown: close connections, stop threads, release
        engine processes, etc.
        
        Should set state to STOPPED.
        """
        pass
    
    @abstractmethod
    def get_move(self, board: chess.Board) -> Optional[chess.Move]:
        """Compute and return a move for the current position.
        
        Called when it's the opponent's turn. May block while thinking.
        Should set state to THINKING while computing, then back to READY.
        
        For asynchronous opponents (like Lichess), this may return None
        immediately and later call the move_callback when the move arrives.
        
        Args:
            board: Current chess position.
        
        Returns:
            The opponent's move, or None if move will be delivered
            asynchronously via move_callback.
        """
        pass
    
    @abstractmethod
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that the player made a move.
        
        Called after the player's move has been validated and applied.
        Stateful opponents (like Lichess) use this to sync state.
        
        Args:
            move: The move the player made.
            board: Board state after the move.
        """
        pass
    
    @abstractmethod
    def on_new_game(self) -> None:
        """Notification that a new game is starting.
        
        Called when the board is reset to starting position.
        Opponents should reset internal state.
        """
        pass
    
    # =========================================================================
    # Optional Methods - May be overridden by subclasses
    # =========================================================================
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred.
        
        Called when the player takes back a move. Not all opponents
        support takeback. Default implementation does nothing.
        
        Args:
            board: Board state after the takeback.
        """
        pass
    
    def on_resign(self) -> None:
        """Notification that the player resigned.
        
        For online opponents, this sends the resignation. Default
        implementation does nothing.
        """
        pass
    
    def on_draw_offer(self) -> None:
        """Notification that the player offered a draw.
        
        For online opponents, this sends the draw offer. Default
        implementation does nothing.
        """
        pass
    
    def supports_takeback(self) -> bool:
        """Whether this opponent supports takeback.
        
        Returns:
            True if takeback is supported, False otherwise.
        """
        return True
    
    def get_info(self) -> dict:
        """Get information about this opponent for display.
        
        Returns:
            Dictionary with opponent info. Keys may include:
            - name: Opponent name
            - rating: ELO rating (if applicable)
            - description: Human-readable description
            - state: Current opponent state
        """
        return {
            'name': self.name,
            'state': self._state.name,
        }
