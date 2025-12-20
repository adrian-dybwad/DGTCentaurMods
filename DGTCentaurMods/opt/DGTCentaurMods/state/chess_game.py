"""
Chess game state.

Holds the authoritative game state: board position, result, and termination.
Widgets observe this state to display the current position and game status.

The chess.Board is owned here - GameManager and other components mutate it
through this state object's methods, which trigger observer notifications.

This module has minimal dependencies (just python-chess and typing) to keep
imports fast for widgets.
"""

import chess
from typing import Optional, Callable, List


class ChessGameState:
    """Observable chess game state.
    
    Holds:
    - The chess.Board (position, legal moves, turn)
    - Game result and termination reason
    
    Observers are notified on:
    - Position changes (moves, takeback, new position)
    - Game over (checkmate, stalemate, resignation, flag, draw)
    
    Thread safety: This class is NOT thread-safe. Callers must ensure
    mutations happen from a single thread or use external synchronization.
    """
    
    def __init__(self):
        """Initialize game state with starting position."""
        self._board = chess.Board()
        self._result: Optional[str] = None  # '1-0', '0-1', '1/2-1/2'
        self._termination: Optional[str] = None  # 'checkmate', 'stalemate', 'resignation', etc.
        
        # Observer callbacks
        self._on_position_change: List[Callable[[], None]] = []
        self._on_game_over: List[Callable[[str, str], None]] = []  # (result, termination)
    
    # -------------------------------------------------------------------------
    # Properties (read-only access to state)
    # -------------------------------------------------------------------------
    
    @property
    def board(self) -> chess.Board:
        """The chess.Board instance. Use for read-only queries.
        
        For mutations, use the state methods (push_move, set_position, etc.)
        to ensure observers are notified.
        """
        return self._board
    
    @property
    def fen(self) -> str:
        """Current position in FEN notation."""
        return self._board.fen()
    
    @property
    def turn(self) -> chess.Color:
        """Which player's turn (chess.WHITE or chess.BLACK)."""
        return self._board.turn
    
    @property
    def turn_name(self) -> str:
        """Turn as string ('white' or 'black')."""
        return 'white' if self._board.turn == chess.WHITE else 'black'
    
    @property
    def legal_moves(self):
        """Generator of legal moves at current position."""
        return self._board.legal_moves
    
    @property
    def move_stack(self) -> List[chess.Move]:
        """List of moves made in this game."""
        return list(self._board.move_stack)
    
    @property
    def is_check(self) -> bool:
        """Whether the current player is in check."""
        return self._board.is_check()
    
    @property
    def is_game_over(self) -> bool:
        """Whether the game has ended (by board state or external result)."""
        return self._board.is_game_over() or self._result is not None
    
    @property
    def result(self) -> Optional[str]:
        """Game result ('1-0', '0-1', '1/2-1/2') or None if ongoing."""
        if self._result is not None:
            return self._result
        outcome = self._board.outcome()
        if outcome is not None:
            return outcome.result()
        return None
    
    @property
    def termination(self) -> Optional[str]:
        """How the game ended ('checkmate', 'stalemate', 'resignation', etc.)."""
        if self._termination is not None:
            return self._termination
        outcome = self._board.outcome()
        if outcome is not None:
            return str(outcome.termination.name).lower()
        return None
    
    # -------------------------------------------------------------------------
    # Observer management
    # -------------------------------------------------------------------------
    
    def on_position_change(self, callback: Callable[[], None]) -> None:
        """Register callback for position changes.
        
        Called after any move, takeback, or position reset.
        
        Args:
            callback: Function with no arguments, called on position change.
        """
        if callback not in self._on_position_change:
            self._on_position_change.append(callback)
    
    def on_game_over(self, callback: Callable[[str, str], None]) -> None:
        """Register callback for game over events.
        
        Args:
            callback: Function(result, termination) called when game ends.
        """
        if callback not in self._on_game_over:
            self._on_game_over.append(callback)
    
    def remove_observer(self, callback: Callable) -> None:
        """Remove a previously registered callback.
        
        Args:
            callback: The callback to remove (from any observer list).
        """
        if callback in self._on_position_change:
            self._on_position_change.remove(callback)
        if callback in self._on_game_over:
            self._on_game_over.remove(callback)
    
    def _notify_position_change(self) -> None:
        """Notify all position change observers."""
        for callback in self._on_position_change:
            try:
                callback()
            except Exception:
                pass  # Don't let observer errors break the state
    
    def _notify_game_over(self, result: str, termination: str) -> None:
        """Notify all game over observers."""
        for callback in self._on_game_over:
            try:
                callback(result, termination)
            except Exception:
                pass
    
    # -------------------------------------------------------------------------
    # State mutations (trigger observer notifications)
    # -------------------------------------------------------------------------
    
    def push_move(self, move: chess.Move) -> None:
        """Push a move onto the board.
        
        Args:
            move: The chess.Move to execute.
            
        Raises:
            ValueError: If move is illegal.
        """
        if move not in self._board.legal_moves:
            raise ValueError(f"Illegal move: {move.uci()}")
        
        self._board.push(move)
        self._notify_position_change()
        
        # Check for game end by board state
        outcome = self._board.outcome()
        if outcome is not None:
            self._result = outcome.result()
            self._termination = str(outcome.termination.name).lower()
            self._notify_game_over(self._result, self._termination)
    
    def push_uci(self, uci: str) -> chess.Move:
        """Push a move by UCI string.
        
        Args:
            uci: Move in UCI format (e.g., 'e2e4', 'e7e8q').
            
        Returns:
            The parsed chess.Move.
            
        Raises:
            ValueError: If UCI is invalid or move is illegal.
        """
        move = chess.Move.from_uci(uci)
        self.push_move(move)
        return move
    
    def pop_move(self) -> Optional[chess.Move]:
        """Pop the last move (takeback).
        
        Returns:
            The popped move, or None if no moves to pop.
        """
        if not self._board.move_stack:
            return None
        
        # Clear any external result on takeback
        self._result = None
        self._termination = None
        
        move = self._board.pop()
        self._notify_position_change()
        return move
    
    def set_position(self, fen: str) -> None:
        """Set the board to a specific position.
        
        Args:
            fen: FEN string of the position.
            
        Raises:
            ValueError: If FEN is invalid.
        """
        self._board.set_fen(fen)
        self._result = None
        self._termination = None
        self._notify_position_change()
    
    def reset(self) -> None:
        """Reset to starting position."""
        self._board.reset()
        self._result = None
        self._termination = None
        self._notify_position_change()
    
    def set_result(self, result: str, termination: str) -> None:
        """Set game result from external event (resignation, flag, draw agreement).
        
        Use this for game endings that aren't determined by board state
        (e.g., resignation, time forfeit, draw by agreement).
        
        Args:
            result: Game result ('1-0', '0-1', '1/2-1/2')
            termination: How game ended ('resignation', 'time_forfeit', 'draw_agreement')
        """
        self._result = result
        self._termination = termination
        self._notify_game_over(result, termination)


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_instance: Optional[ChessGameState] = None


def get_chess_game() -> ChessGameState:
    """Get the singleton ChessGameState instance.
    
    Returns:
        The global ChessGameState instance.
    """
    global _instance
    if _instance is None:
        _instance = ChessGameState()
    return _instance


def reset_chess_game() -> ChessGameState:
    """Reset the singleton to a fresh instance.
    
    Primarily for testing. Creates a new instance and returns it.
    
    Returns:
        The new ChessGameState instance.
    """
    global _instance
    _instance = ChessGameState()
    return _instance
