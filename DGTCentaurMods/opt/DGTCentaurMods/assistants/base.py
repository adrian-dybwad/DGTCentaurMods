# Assistant Base Class
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Abstract base class for all assistants. An assistant helps the user
# play by providing suggestions, hints, or guidance without making
# moves itself.
#
# Designed to be extendable by users who want to implement custom assistants.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, List
import chess


class SuggestionType(Enum):
    """Types of suggestions an assistant can provide.
    
    - PIECE_TYPE: Suggests which piece type to move (e.g., Hand+Brain mode).
    - MOVE: Suggests a specific move (e.g., hint button).
    - SQUARES: Highlights squares without specifying a move.
    - EVALUATION: Provides position evaluation without move suggestion.
    - TEXT: Text-based advice or coaching.
    """
    PIECE_TYPE = auto()
    MOVE = auto()
    SQUARES = auto()
    EVALUATION = auto()
    TEXT = auto()


@dataclass
class Suggestion:
    """A suggestion from an assistant.
    
    Attributes:
        suggestion_type: What kind of suggestion this is.
        piece_type: For PIECE_TYPE suggestions, which piece (K, Q, R, B, N, P).
        move: For MOVE suggestions, the suggested move.
        squares: For SQUARES/PIECE_TYPE, list of square indices to highlight.
        evaluation: For EVALUATION, centipawn score or mate score.
        text: For TEXT suggestions, the advice text.
        confidence: Optional confidence level (0.0 to 1.0).
    """
    suggestion_type: SuggestionType
    piece_type: Optional[str] = None
    move: Optional[chess.Move] = None
    squares: List[int] = field(default_factory=list)
    evaluation: Optional[int] = None
    text: Optional[str] = None
    confidence: Optional[float] = None
    
    @classmethod
    def piece(cls, piece_symbol: str, squares: List[int]) -> 'Suggestion':
        """Create a piece type suggestion (e.g., for Hand+Brain).
        
        Args:
            piece_symbol: Piece symbol (K, Q, R, B, N, P).
            squares: Square indices containing that piece type.
        
        Returns:
            Suggestion for the piece type.
        """
        return cls(
            suggestion_type=SuggestionType.PIECE_TYPE,
            piece_type=piece_symbol.upper(),
            squares=squares
        )
    
    @classmethod
    def hint_move(cls, move: chess.Move, confidence: float = None) -> 'Suggestion':
        """Create a move suggestion (e.g., for hint button).
        
        Args:
            move: The suggested move.
            confidence: Optional confidence level.
        
        Returns:
            Suggestion for the move.
        """
        return cls(
            suggestion_type=SuggestionType.MOVE,
            move=move,
            squares=[move.from_square, move.to_square],
            confidence=confidence
        )
    
    @classmethod
    def highlight(cls, squares: List[int]) -> 'Suggestion':
        """Create a squares highlight suggestion.
        
        Args:
            squares: Square indices to highlight.
        
        Returns:
            Suggestion to highlight squares.
        """
        return cls(
            suggestion_type=SuggestionType.SQUARES,
            squares=squares
        )
    
    @classmethod
    def eval(cls, centipawns: int) -> 'Suggestion':
        """Create an evaluation suggestion.
        
        Args:
            centipawns: Position evaluation in centipawns (positive = white better).
        
        Returns:
            Suggestion with evaluation.
        """
        return cls(
            suggestion_type=SuggestionType.EVALUATION,
            evaluation=centipawns
        )
    
    @classmethod
    def advice(cls, text: str) -> 'Suggestion':
        """Create a text advice suggestion.
        
        Args:
            text: The advice text.
        
        Returns:
            Suggestion with text advice.
        """
        return cls(
            suggestion_type=SuggestionType.TEXT,
            text=text
        )


@dataclass
class AssistantConfig:
    """Base configuration for assistants.
    
    Subclasses should extend this with assistant-specific settings.
    
    Attributes:
        name: Human-readable name for display/logging.
        time_limit_seconds: Maximum time for computing suggestions.
        auto_suggest: If True, suggestions are provided automatically on each turn.
                     If False, suggestions only provided on request.
    """
    name: str = "Assistant"
    time_limit_seconds: float = 2.0
    auto_suggest: bool = True


class Assistant(ABC):
    """Abstract base class for chess assistants.
    
    An assistant helps the user play by providing suggestions. Unlike
    opponents, assistants don't make moves - they provide guidance that
    the user can choose to follow or ignore.
    
    Subclasses must implement:
    - start(): Initialize the assistant
    - stop(): Clean shutdown
    - get_suggestion(): Compute and return a suggestion for the position
    - on_player_move(): Notification when player makes a move
    - on_new_game(): Notification when a new game starts
    
    Thread Safety:
    Assistants may be called from multiple threads. Implementations should
    ensure thread safety, especially for get_suggestion() which may run
    in a background thread.
    
    Extension Point:
    Users can create custom assistants by subclassing this class. The
    assistant will be discovered and usable through the normal game flow.
    """
    
    def __init__(self, config: Optional[AssistantConfig] = None):
        """Initialize the assistant.
        
        Args:
            config: Configuration for this assistant. If None, uses defaults.
        """
        self._config = config or AssistantConfig()
        self._active = False
        self._error_message: Optional[str] = None
        
        # Callbacks set by the game coordinator
        self._suggestion_callback: Optional[Callable[[Suggestion], None]] = None
        self._status_callback: Optional[Callable[[str], None]] = None
    
    @property
    def name(self) -> str:
        """Human-readable name of this assistant."""
        return self._config.name
    
    @property
    def is_active(self) -> bool:
        """Whether the assistant is active and providing suggestions."""
        return self._active
    
    @property
    def auto_suggest(self) -> bool:
        """Whether suggestions are provided automatically."""
        return self._config.auto_suggest
    
    @property
    def error_message(self) -> Optional[str]:
        """Error message if initialization failed, None otherwise."""
        return self._error_message
    
    def set_suggestion_callback(self, callback: Callable[[Suggestion], None]) -> None:
        """Set callback for when assistant has a suggestion.
        
        The callback receives a Suggestion object. This is used for
        asynchronous assistants that compute suggestions in the background.
        
        Args:
            callback: Function to call with the suggestion.
        """
        self._suggestion_callback = callback
    
    def set_status_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for status updates.
        
        Used to display status messages during initialization.
        
        Args:
            callback: Function to call with status text.
        """
        self._status_callback = callback
    
    def _report_status(self, message: str) -> None:
        """Report a status message via the callback if set.
        
        Args:
            message: Status message to report.
        """
        if self._status_callback:
            self._status_callback(message)
    
    def _report_suggestion(self, suggestion: Suggestion) -> None:
        """Report a suggestion via the callback if set.
        
        Args:
            suggestion: The suggestion to report.
        """
        if self._suggestion_callback:
            self._suggestion_callback(suggestion)
    
    # =========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # =========================================================================
    
    @abstractmethod
    def start(self) -> bool:
        """Initialize and start the assistant.
        
        Performs any async initialization: loading engine, etc.
        
        Returns:
            True if started successfully, False on error.
        """
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Stop the assistant and release resources.
        
        Clean shutdown: stop threads, release engine processes, etc.
        """
        pass
    
    @abstractmethod
    def get_suggestion(self, board: chess.Board, for_color: chess.Color) -> Optional[Suggestion]:
        """Compute and return a suggestion for the current position.
        
        Called when the user requests a suggestion or when it's the
        user's turn (if auto_suggest is True). May block while computing.
        
        For asynchronous assistants, this may return None immediately
        and later call the suggestion_callback when ready.
        
        Args:
            board: Current chess position.
            for_color: Which color to provide suggestions for. Allows the
                      caller to specify context (e.g., player's color) without
                      the assistant needing to store this state.
        
        Returns:
            A Suggestion object, or None if suggestion will be delivered
            asynchronously via suggestion_callback.
        """
        pass
    
    @abstractmethod
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that the player made a move.
        
        Called after the player's move has been validated and applied.
        Assistants may use this to clear previous suggestions.
        
        Args:
            move: The move the player made.
            board: Board state after the move.
        """
        pass
    
    @abstractmethod
    def on_new_game(self) -> None:
        """Notification that a new game is starting.
        
        Called when the board is reset to starting position.
        Assistants should reset internal state and clear suggestions.
        """
        pass
    
    # =========================================================================
    # Optional Methods - May be overridden by subclasses
    # =========================================================================
    
    def on_opponent_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that the opponent made a move.
        
        Called after the opponent's move. Assistants may use this to
        prepare suggestions for the player's response.
        
        Args:
            move: The move the opponent made.
            board: Board state after the move.
        """
        pass
    
    def on_takeback(self, board: chess.Board) -> None:
        """Notification that a takeback occurred.
        
        Args:
            board: Board state after the takeback.
        """
        pass
    
    def clear_suggestion(self) -> None:
        """Clear any current suggestion display.
        
        Called when the suggestion should be removed from display
        (e.g., player started a different move).
        """
        if self._suggestion_callback:
            # Empty suggestion signals clear
            self._suggestion_callback(Suggestion(suggestion_type=SuggestionType.SQUARES, squares=[]))
    
    def get_info(self) -> dict:
        """Get information about this assistant for display.
        
        Returns:
            Dictionary with assistant info. Keys may include:
            - name: Assistant name
            - description: Human-readable description
            - auto_suggest: Whether suggestions are automatic
        """
        return {
            'name': self.name,
            'auto_suggest': self.auto_suggest,
            'active': self._active,
        }
