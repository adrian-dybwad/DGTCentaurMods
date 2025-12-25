"""Starting position detection helpers.

Multiple GameManager flows treat the physical board being in the standard starting
position as a signal to abandon/reset the current game.

This module centralizes that policy check.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from universalchess.state.chess_game import ChessGameState


def is_starting_position_state(
    *,
    current_state: Optional[Sequence[int]],
    board_size: int,
) -> bool:
    """Return True if the physical board state represents the standard starting position."""
    if current_state is None or len(current_state) != board_size:
        return False
    return ChessGameState.is_starting_position(current_state)


def reset_game_if_starting_position(
    *,
    current_state: Optional[Sequence[int]],
    board_size: int,
    reset_game_fn: Callable[[], None],
) -> bool:
    """Reset the game if the physical board is in the starting position.

    Returns:
        True if reset was triggered, False otherwise.
    """
    if not is_starting_position_state(current_state=current_state, board_size=board_size):
        return False

    reset_game_fn()
    return True


__all__ = ["is_starting_position_state", "reset_game_if_starting_position"]


