"""Correction guidance algorithms for physical board mismatch.

This module is responsible for:
- computing missing/extra squares from piece-presence states
- detecting the "kings in center" gesture from state deltas
- choosing a piece to guide using Hungarian assignment (SciPy) when available
- driving LEDs via the injected board module

It is intentionally independent from GameManager so it can be tested in isolation.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import chess

from universalchess.board.logging import log
from universalchess.utils.led import LedCallbacks

from .move_state import CENTER_SQUARES, BOARD_WIDTH


def compute_state_deltas(
    *,
    current_state: Sequence[int],
    expected_state: Sequence[int],
) -> Tuple[List[int], List[int]]:
    """Compute missing and extra squares from piece-presence states."""
    missing_squares: List[int] = []
    extra_squares: List[int] = []

    for i in range(len(expected_state)):
        if expected_state[i] == 1 and current_state[i] == 0:
            missing_squares.append(i)
        elif expected_state[i] == 0 and current_state[i] == 1:
            extra_squares.append(i)

    return missing_squares, extra_squares


def check_kings_in_center_from_state(
    *,
    chess_board: chess.Board,
    missing_squares: List[int],
    extra_squares: List[int],
) -> bool:
    """Detect kings-in-center gesture from state deltas.

    The gesture is detected when:
    - both king squares are missing (kings lifted)
    - at least 2 of d4/d5/e4/e5 are extra (kings placed in center area)
    """
    # Don't trigger if the game is already over
    outcome = chess_board.outcome(claim_draw=True)
    if outcome is not None:
        return False

    white_king_square = chess_board.king(chess.WHITE)
    black_king_square = chess_board.king(chess.BLACK)
    if white_king_square is None or black_king_square is None:
        return False

    if not (white_king_square in missing_squares and black_king_square in missing_squares):
        return False

    center_extras = [sq for sq in extra_squares if sq in CENTER_SQUARES]
    return len(center_extras) >= 2


def _square_to_row_col(square_idx: int) -> Tuple[int, int]:
    return (square_idx // BOARD_WIDTH), (square_idx % BOARD_WIDTH)


def _manhattan_distance(sq1: int, sq2: int) -> int:
    r1, c1 = _square_to_row_col(sq1)
    r2, c2 = _square_to_row_col(sq2)
    return abs(r1 - r2) + abs(c1 - c2)


def choose_guidance_pair(
    *,
    extra_squares: List[int],
    missing_squares: List[int],
    get_linear_sum_assignment_fn: Callable[[], Optional[Callable]],
) -> Tuple[int, int]:
    """Choose a (from_square, to_square) guidance pair."""
    if len(extra_squares) == 1 and len(missing_squares) == 1:
        return extra_squares[0], missing_squares[0]

    linear_sum_assignment = get_linear_sum_assignment_fn()
    if linear_sum_assignment is not None:
        # Import numpy only when SciPy is available to keep optional deps localized.
        import numpy as np

        n_extra = len(extra_squares)
        n_missing = len(missing_squares)
        costs = np.zeros((n_extra, n_missing))
        for i, extra_sq in enumerate(extra_squares):
            for j, missing_sq in enumerate(missing_squares):
                costs[i, j] = _manhattan_distance(extra_sq, missing_sq)
        row_ind, col_ind = linear_sum_assignment(costs)
        return extra_squares[int(row_ind[0])], missing_squares[int(col_ind[0])]

    # Fallback: guide first extra piece to nearest missing square
    from_idx = extra_squares[0]
    min_dist = 10**9
    to_idx = missing_squares[0]
    for missing_sq in missing_squares:
        dist = _manhattan_distance(from_idx, missing_sq)
        if dist < min_dist:
            min_dist = dist
            to_idx = missing_sq
    return from_idx, to_idx


def provide_correction_guidance(
    *,
    board_module,
    led: LedCallbacks,
    chess_board: chess.Board,
    current_state: Sequence[int],
    expected_state: Sequence[int],
    get_linear_sum_assignment_fn: Callable[[], Optional[Callable]],
    on_kings_in_center: Optional[Callable[[], None]],
    on_kings_in_center_detected: Callable[[], None],
) -> None:
    """Drive LED guidance for correcting misplaced pieces."""
    if current_state is None or expected_state is None:
        return
    if len(current_state) != 64 or len(expected_state) != 64:
        return

    missing_squares, extra_squares = compute_state_deltas(
        current_state=current_state, expected_state=expected_state
    )

    if not missing_squares and not extra_squares:
        led.off()
        return

    if on_kings_in_center is not None and check_kings_in_center_from_state(
        chess_board=chess_board,
        missing_squares=missing_squares,
        extra_squares=extra_squares,
    ):
        log.info("[GameManager._provide_correction_guidance] Kings-in-center gesture detected")
        on_kings_in_center_detected()
        return

    log.warning(
        f"[GameManager._provide_correction_guidance] Found {len(extra_squares)} wrong pieces, "
        f"{len(missing_squares)} missing pieces"
    )

    if extra_squares and missing_squares:
        from_idx, to_idx = choose_guidance_pair(
            extra_squares=extra_squares,
            missing_squares=missing_squares,
            get_linear_sum_assignment_fn=get_linear_sum_assignment_fn,
        )
        led.off()
        led.from_to_fast(from_idx, to_idx, repeat=0)
        log.warning(
            "[GameManager._provide_correction_guidance] Guiding piece from "
            f"{chess.square_name(from_idx)} to {chess.square_name(to_idx)}"
        )
        return

    # Only pieces missing or only extra pieces
    if missing_squares:
        led.off()
        for idx in missing_squares:
            led.single_fast(idx, repeat=0)
        log.warning(
            "[GameManager._provide_correction_guidance] Pieces missing at: "
            f"{[chess.square_name(sq) for sq in missing_squares]}"
        )
        return

    if extra_squares:
        led.off()
        led.array_fast(extra_squares, repeat=0)
        log.warning(
            "[GameManager._provide_correction_guidance] Extra pieces at: "
            f"{[chess.square_name(sq) for sq in extra_squares]}"
        )


__all__ = [
    "compute_state_deltas",
    "check_kings_in_center_from_state",
    "choose_guidance_pair",
    "provide_correction_guidance",
]


