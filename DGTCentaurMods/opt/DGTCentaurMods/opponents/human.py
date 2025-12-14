# Human Opponent (Two-Player Mode)
#
# This file is part of the DGTCentaurUniversal project
# ( https://github.com/adrian-dybwad/DGTCentaurUniversal )
#
# Implements a null opponent for two-player mode where both sides
# are played by humans on the physical board. No computer moves.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from dataclasses import dataclass
from typing import Optional

import chess

from DGTCentaurMods.board.logging import log
from .base import Opponent, OpponentConfig, OpponentState


@dataclass
class HumanConfig(OpponentConfig):
    """Configuration for human opponent (two-player mode).
    
    In two-player mode, both sides are human, so the opponent
    doesn't generate any moves.
    """
    name: str = "Human"


class HumanOpponent(Opponent):
    """Null opponent for two-player mode.
    
    In two-player mode, both white and black are played by humans
    on the physical board. This opponent never generates moves -
    it simply tracks game state for consistency.
    
    This follows the Null Object pattern: it provides a valid
    Opponent interface but performs no actions. This allows the
    game coordinator to treat two-player mode the same as
    engine mode without special-casing.
    """
    
    def __init__(self, config: Optional[HumanConfig] = None):
        """Initialize the human opponent.
        
        Args:
            config: Configuration. If None, uses defaults.
        """
        super().__init__(config or HumanConfig())
    
    def start(self) -> bool:
        """Start the human opponent.
        
        Always succeeds immediately - no initialization needed.
        
        Returns:
            True always.
        """
        log.info("[HumanOpponent] Two-player mode active - no computer opponent")
        self._set_state(OpponentState.READY)
        return True
    
    def stop(self) -> None:
        """Stop the human opponent.
        
        Nothing to clean up.
        """
        log.info("[HumanOpponent] Stopping two-player mode")
        self._set_state(OpponentState.STOPPED)
    
    def get_move(self, board: chess.Board) -> Optional[chess.Move]:
        """Get the opponent's move.
        
        In two-player mode, this is never called for computer moves.
        Returns None - both players move on the physical board.
        
        Args:
            board: Current chess position.
        
        Returns:
            None always (both players are human).
        """
        log.debug("[HumanOpponent] get_move called - ignoring (two-player mode)")
        return None
    
    def on_player_move(self, move: chess.Move, board: chess.Board) -> None:
        """Notification that a player made a move.
        
        In two-player mode, both moves are "player" moves.
        
        Args:
            move: The move made.
            board: Board state after the move.
        """
        log.debug(f"[HumanOpponent] Move: {move.uci()}")
    
    def on_new_game(self) -> None:
        """Notification that a new game is starting."""
        log.info("[HumanOpponent] New game")
    
    def supports_takeback(self) -> bool:
        """Two-player mode always supports takeback."""
        return True
    
    def get_info(self) -> dict:
        """Get information about this opponent."""
        info = super().get_info()
        info.update({
            'description': 'Two-player mode (no computer)',
            'mode': '2player',
        })
        return info
