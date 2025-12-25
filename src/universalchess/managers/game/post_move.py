"""Post-move helpers for GameManager.

These helpers encapsulate side-effect steps that run after a move has been applied:
- validating that the physical board matches the logical board (low priority)
- handling game end (beep + result update)

They are designed to be called from GameManager's serial task worker to preserve
ordering with other side effects.
"""

from __future__ import annotations

from typing import Callable, Optional

from universalchess.board.logging import log
from universalchess.state.chess_game import ChessGameState


def validate_physical_board_after_move(
    *,
    board_module,
    move_uci: str,
    chess_board,
    chess_board_to_state_fn: Callable,
    enter_correction_mode_fn: Callable[[], None],
    provide_correction_guidance_fn: Callable[[bytes, bytes], None],
) -> None:
    """Validate that physical board matches logical board after a move.

    Uses low-priority board polling to avoid delaying piece event detection.
    If the board is busy with polling, validation may be skipped (None response).
    """
    try:
        current_physical_state = board_module.getChessStateLowPriority()
        if current_physical_state is None:
            return

        expected_logical_state = chess_board_to_state_fn(chess_board)
        if expected_logical_state is None:
            return

        if not ChessGameState.states_match(current_physical_state, expected_logical_state):
            log.warning(
                f"[GameManager.async] Physical board mismatch after {move_uci}, entering correction mode"
            )
            enter_correction_mode_fn()
            provide_correction_guidance_fn(current_physical_state, expected_logical_state)
    except Exception as e:
        log.debug(f"[GameManager.async] Error validating physical board: {e}")


def handle_game_end(
    *,
    board_module,
    result_string: str,
    termination: str,
    update_game_result_fn: Callable[[str, str, str], None],
    context: str,
) -> None:
    """Handle end-of-game side effects."""
    board_module.beep(board_module.SOUND_GENERAL, event_type="game_event")
    update_game_result_fn(result_string, termination, context)


__all__ = [
    "validate_physical_board_after_move",
    "handle_game_end",
]


