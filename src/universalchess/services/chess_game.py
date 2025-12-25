"""
Chess game service.

Manages game lifecycle, coordinates with ChessGameState, and writes FEN log.
"""

from typing import Optional

try:
    from universalchess.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

from universalchess.state import get_chess_game as get_game_state
from universalchess.paths import write_fen_log


class ChessGameService:
    """Service managing chess game lifecycle and FEN log."""
    
    def __init__(self):
        """Initialize the chess game service."""
        self._state = get_game_state()
        
        # Register for position changes to write FEN log
        self._state.on_position_change(self._on_position_change)
    
    # -------------------------------------------------------------------------
    # Properties (delegate to state for reads)
    # -------------------------------------------------------------------------
    
    @property
    def fen(self) -> str:
        """Current position in FEN notation."""
        return self._state.fen
    
    @property
    def turn(self):
        """Which player's turn."""
        return self._state.turn
    
    @property
    def is_game_over(self) -> bool:
        """Whether the game has ended."""
        return self._state.is_game_over
    
    @property
    def result(self) -> Optional[str]:
        """Game result, or None if ongoing."""
        return self._state.result
    
    # -------------------------------------------------------------------------
    # Game lifecycle
    # -------------------------------------------------------------------------
    
    def new_game(self, fen: Optional[str] = None) -> None:
        """Start a new game.
        
        Args:
            fen: Starting position FEN, or None for standard starting position.
        """
        if fen:
            self._state.set_position(fen)
        else:
            self._state.reset()
        
        log.info(f"[ChessGameService] New game started: {self._state.fen}")
    
    def end_game(self, result: str, termination: str) -> None:
        """End the current game.
        
        Args:
            result: Game result ('1-0', '0-1', '1/2-1/2')
            termination: How game ended ('resignation', 'time_forfeit', etc.)
        """
        self._state.set_result(result, termination)
        log.info(f"[ChessGameService] Game ended: {result} ({termination})")
    
    # -------------------------------------------------------------------------
    # Move operations (delegate to state)
    # -------------------------------------------------------------------------
    
    def push_move(self, move) -> None:
        """Push a move onto the board.
        
        Args:
            move: chess.Move to execute.
        """
        self._state.push_move(move)
    
    def push_uci(self, uci: str):
        """Push a move by UCI string.
        
        Args:
            uci: Move in UCI format.
            
        Returns:
            The parsed chess.Move.
        """
        return self._state.push_uci(uci)
    
    def pop_move(self):
        """Pop the last move (takeback).
        
        Returns:
            The popped move, or None.
        """
        return self._state.pop_move()
    
    def set_position(self, fen: str) -> None:
        """Set the board to a specific position.
        
        Args:
            fen: FEN string of the position.
        """
        self._state.set_position(fen)
    
    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------
    
    def _on_position_change(self) -> None:
        """Called when position changes. Writes FEN log for external consumers."""
        try:
            write_fen_log(self._state.fen)
        except Exception as e:
            log.debug(f"[ChessGameService] Error writing FEN log: {e}")


# -----------------------------------------------------------------------------
# Singleton instance
# -----------------------------------------------------------------------------

_instance: Optional[ChessGameService] = None


def get_chess_game_service() -> ChessGameService:
    """Get the singleton ChessGameService instance.
    
    Returns:
        The global ChessGameService instance.
    """
    global _instance
    if _instance is None:
        _instance = ChessGameService()
    return _instance
