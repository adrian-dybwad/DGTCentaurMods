# Human Player
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# A human player whose moves come from the physical board.
# Moves are constructed from piece lift/place events.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from dataclasses import dataclass
from typing import Optional

import chess

from DGTCentaurMods.board.logging import log
from .base import Player, PlayerConfig, PlayerState, PlayerType


@dataclass 
class HumanPlayerConfig(PlayerConfig):
    """Configuration for human player.
    
    Human players don't need much configuration - their moves
    come from the physical board.
    """
    name: str = "Human"


class HumanPlayer(Player):
    """A player whose moves come from piece events on the physical board.
    
    Human players construct moves from lift/place events:
    1. Piece lifted from square A
    2. Piece placed on square B
    3. Move A->B is submitted via callback
    
    The game then validates the move (legal or not) and either
    executes it or enters correction mode.
    
    Key behaviors:
    - on_piece_event() tracks lifts/places and forms moves
    - request_move() resets state for new turn
    - Submits moves via move_callback like all players
    """
    
    def __init__(self, config: Optional[HumanPlayerConfig] = None):
        """Initialize the human player.
        
        Args:
            config: Configuration. If None, uses defaults.
        """
        super().__init__(config or HumanPlayerConfig())
        
        # Track piece events to construct moves
        self._lifted_square: Optional[int] = None
    
    @property
    def player_type(self) -> PlayerType:
        """Human player type."""
        return PlayerType.HUMAN
    
    def start(self) -> bool:
        """Start the human player.
        
        Always succeeds immediately - no initialization needed.
        Human is always ready to play.
        
        Returns:
            True always.
        """
        color_name = 'White' if self._color == chess.WHITE else 'Black' if self._color == chess.BLACK else 'Unknown'
        log.info(f"[HumanPlayer] {color_name} player ready")
        self._set_state(PlayerState.READY)
        return True
    
    def stop(self) -> None:
        """Stop the human player.
        
        Nothing to clean up.
        """
        log.debug("[HumanPlayer] Stopping")
        self._lifted_square = None
        self._set_state(PlayerState.STOPPED)
    
    def request_move(self, board: chess.Board) -> None:
        """Called when it's this player's turn.
        
        Resets state to prepare for receiving piece events.
        
        Args:
            board: Current chess position.
        """
        self._lifted_square = None
        log.debug("[HumanPlayer] Turn started, waiting for piece events")
    
    def on_piece_event(self, event_type: str, square: int, board: chess.Board) -> None:
        """Handle a piece event from the physical board.
        
        Constructs a move from lift/place sequence:
        - lift: remember the square
        - place: form move from lifted square to placed square, submit
        
        Args:
            event_type: "lift" or "place"
            square: The square index (0-63)
            board: Current chess position
        """
        if event_type == "lift":
            self._lifted_square = square
            log.debug(f"[HumanPlayer] Piece lifted from {chess.square_name(square)}")
        
        elif event_type == "place":
            if self._lifted_square is not None:
                # Form the move
                move = chess.Move(self._lifted_square, square)
                log.info(f"[HumanPlayer] Move formed: {move.uci()}")
                
                # Reset state
                from_sq = self._lifted_square
                self._lifted_square = None
                
                # Submit the move
                if self._move_callback:
                    self._move_callback(move)
                else:
                    log.warning("[HumanPlayer] No move callback set, cannot submit move")
            else:
                log.debug(f"[HumanPlayer] Piece placed on {chess.square_name(square)} but no lift tracked")
    
    def on_move_made(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that a move was made.
        
        Args:
            move: The move that was made.
            board: Board state after the move.
        """
        log.debug(f"[HumanPlayer] Move made: {move.uci()}")
        # Reset state after move is made
        self._lifted_square = None
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting."""
        log.debug("[HumanPlayer] New game")
        self._lifted_square = None
    
    def supports_takeback(self) -> bool:
        """Human players always support takeback."""
        return True
    
    def get_info(self) -> dict:
        """Get information about this player."""
        info = super().get_info()
        info.update({
            'description': 'Human player (physical board)',
        })
        return info
