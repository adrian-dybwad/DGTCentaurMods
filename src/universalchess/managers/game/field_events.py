"""Field event routing for GameManager.

This module extracts the orchestration of physical board field events (LIFT/PLACE)
from `GameManager._process_field_event` while preserving behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import chess

from universalchess.board.logging import log
from universalchess.managers.events import EVENT_LIFT_PIECE, EVENT_PLACE_PIECE
from universalchess.state.chess_game import ChessGameState

from .move_state import INVALID_SQUARE


@dataclass(frozen=True)
class FieldEventContext:
    chess_board: chess.Board
    move_state: object
    correction_mode: object
    player_manager: object
    board_module: object

    # Callbacks
    event_callback: Optional[Callable]
    enter_correction_mode_fn: Callable[[], None]
    provide_correction_guidance_fn: Callable[[object, object], None]
    handle_field_event_in_correction_mode_fn: Callable[[int, int, float], None]
    handle_piece_event_without_player_fn: Callable[[int], None]
    on_piece_event_fn: Callable[[str, int, chess.Board], None]
    handle_king_lift_resign_fn: Callable[[int, object], None]
    execute_pending_move_fn: Callable[[chess.Move], None]

    # Menu state and callbacks
    get_kings_in_center_menu_active_fn: Callable[[], bool]
    set_kings_in_center_menu_active_fn: Callable[[bool], None]
    on_kings_in_center_cancel_fn: Optional[Callable[[], None]]

    get_king_lift_resign_menu_active_fn: Callable[[], bool]
    set_king_lift_resign_menu_active_fn: Callable[[bool], None]
    on_king_lift_resign_cancel_fn: Optional[Callable[[], None]]

    # Expected state helper
    chess_board_to_state_fn: Callable[[chess.Board], Optional[bytearray]]


def process_field_event(
    ctx: FieldEventContext, piece_event: int, field: int, time_in_seconds: float
) -> None:
    """Process one field event (LIFT=0, PLACE=1)."""
    field_name = chess.square_name(field)

    # Piece color selection rules:
    # - LIFT: use color_at(field)
    # - PLACE: use stored source_piece_color (captures), fallback to color_at(field)
    if piece_event == 0:
        if ctx.event_callback is not None:
            ctx.event_callback(EVENT_LIFT_PIECE, piece_event, field, time_in_seconds)
        piece_color = ctx.chess_board.color_at(field)
    else:
        if ctx.event_callback is not None:
            ctx.event_callback(EVENT_PLACE_PIECE, piece_event, field, time_in_seconds)
        if getattr(ctx.move_state, "source_piece_color", None) is not None:
            piece_color = ctx.move_state.source_piece_color
        else:
            piece_color = ctx.chess_board.color_at(field)

    log.info(
        f"[GameManager.receive_field] piece_event={piece_event} field={field} fieldname={field_name} "
        f"color_at={'White' if piece_color else 'Black'} time_in_seconds={time_in_seconds}"
    )

    is_lift = piece_event == 0

    # When a resign menu is active (kings-in-center or king-lift), check for:
    # 1. Board corrected (pieces returned to position) → cancel menu
    # 2. LIFT event → cancel menu and enter correction mode to guide pieces back
    if ctx.get_kings_in_center_menu_active_fn() or ctx.get_king_lift_resign_menu_active_fn():
        expected_state = ctx.chess_board_to_state_fn(ctx.chess_board)
        current_state = ctx.board_module.getChessState()

        if current_state is not None and expected_state is not None:
            if ChessGameState.states_match(current_state, expected_state):
                log.info("[GameManager.receive_field] Board corrected while resign menu active - cancelling menu")
                if ctx.get_kings_in_center_menu_active_fn():
                    ctx.set_kings_in_center_menu_active_fn(False)
                    if ctx.on_kings_in_center_cancel_fn:
                        ctx.on_kings_in_center_cancel_fn()
                if ctx.get_king_lift_resign_menu_active_fn():
                    ctx.set_king_lift_resign_menu_active_fn(False)
                    ctx.move_state._cancel_king_lift_timer()
                    ctx.move_state.king_lifted_square = INVALID_SQUARE
                    ctx.move_state.king_lifted_color = None
                    if ctx.on_king_lift_resign_cancel_fn:
                        ctx.on_king_lift_resign_cancel_fn()
                return

        if is_lift:
            log.info(
                "[GameManager.receive_field] Piece lifted while resign menu active - cancelling menu and entering correction mode"
            )
            if ctx.get_kings_in_center_menu_active_fn():
                ctx.set_kings_in_center_menu_active_fn(False)
                if ctx.on_kings_in_center_cancel_fn:
                    ctx.on_kings_in_center_cancel_fn()
            if ctx.get_king_lift_resign_menu_active_fn():
                ctx.set_king_lift_resign_menu_active_fn(False)
                ctx.move_state._cancel_king_lift_timer()
                ctx.move_state.king_lifted_square = INVALID_SQUARE
                ctx.move_state.king_lifted_color = None
                if ctx.on_king_lift_resign_cancel_fn:
                    ctx.on_king_lift_resign_cancel_fn()
            ctx.enter_correction_mode_fn()
            if current_state is not None and expected_state is not None:
                ctx.provide_correction_guidance_fn(current_state, expected_state)
            return

        return  # Skip all other processing while menu is active (PLACE events)

    # Handle correction mode - piece events help correct the board
    if ctx.correction_mode.is_active:
        ctx.handle_field_event_in_correction_mode_fn(piece_event, field, time_in_seconds)
        return

    # If no PlayerManager, handle piece events directly
    if not ctx.player_manager:
        if not is_lift:
            ctx.handle_piece_event_without_player_fn(field)
        return

    # BOARD STATE VALIDATION FOR PENDING MOVES (must happen BEFORE forwarding to player)
    # If there's a pending move (engine/Lichess) and the physical board matches the
    # expected state AFTER the move, execute it directly regardless of event sequence.
    # This handles nudges, missed lifts, or any other noise - if the board is right, the move succeeded.
    # 
    # This check MUST happen before on_piece_event_fn() because otherwise the player
    # may form an incorrect move from a noisy event sequence and report an error.
    #
    # For captures: require at least one event (LIFT or PLACE) on the capture square
    # before using the board state shortcut. This ensures the user has interacted with
    # the captured piece (even if some events were missed/fumbled).
    pending_move = ctx.player_manager.get_current_pending_move(ctx.chess_board)
    if pending_move is not None:
        is_capture = ctx.chess_board.is_capture(pending_move)
        capture_square = pending_move.to_square if is_capture else None
        
        # For captures, record any event on the capture square (LIFT or PLACE)
        if is_capture and field == capture_square:
            if not ctx.move_state.has_seen_capture_square_event(capture_square):
                ctx.move_state.record_capture_square_event(capture_square)
                log.debug(f"[GameManager.receive_field] Recorded {'LIFT' if is_lift else 'PLACE'} event on "
                         f"capture square {chess.square_name(capture_square)}")
        
        # Board state check only on PLACE events (not LIFT)
        if not is_lift:
            # For captures: only use shortcut if we've seen an event on the capture square
            can_use_shortcut = not is_capture or ctx.move_state.has_seen_capture_square_event(capture_square)
            
            if can_use_shortcut:
                # Create expected board state after the pending move
                expected_board_after = ctx.chess_board.copy()
                expected_board_after.push(pending_move)
                expected_state_after = ctx.chess_board_to_state_fn(expected_board_after)
                
                # Get current physical state
                current_physical_state = ctx.board_module.getChessState()
                
                if expected_state_after is not None and current_physical_state is not None:
                    if ChessGameState.states_match(current_physical_state, expected_state_after):
                        log.info(
                            f"[GameManager.receive_field] Physical board matches expected state after {pending_move.uci()} - "
                            "executing pending move directly"
                        )
                        ctx.execute_pending_move_fn(pending_move)
                        return
            elif is_capture:
                log.debug(f"[GameManager.receive_field] Pending capture {pending_move.uci()} - "
                         "waiting for event on capture square")

    # Check for "wrong piece lifted during forced move" on LIFT events
    # If there's a pending move (engine/Lichess) and the user lifts a piece that is NOT
    # the source of the pending move AND NOT the capture target, enter correction mode.
    # This prevents confusion when the user picks up the wrong piece during a forced move.
    # 
    # Valid lifts during a pending move:
    # - The piece that needs to move (pending_move.from_square)
    # - The piece being captured (pending_move.to_square, if it's a capture)
    if is_lift and pending_move is not None and piece_color is not None:
        pending_from_square = pending_move.from_square
        pending_to_square = pending_move.to_square
        is_pending_capture = ctx.chess_board.is_capture(pending_move)
        
        # Allow lifting from: source square OR capture target square
        is_valid_lift = (field == pending_from_square or 
                         (is_pending_capture and field == pending_to_square))
        
        if not is_valid_lift:
            pending_piece = ctx.chess_board.piece_at(pending_from_square)
            pending_piece_name = chess.piece_name(pending_piece.piece_type) if pending_piece else "piece"
            log.warning(
                f"[GameManager.receive_field] Wrong piece lifted at {chess.square_name(field)} - "
                f"expected {pending_piece_name} at {chess.square_name(pending_from_square)} for pending move {pending_move.uci()} - "
                "entering correction mode"
            )
            ctx.board_module.beep(ctx.board_module.SOUND_WRONG_MOVE, event_type="error")
            ctx.enter_correction_mode_fn()
            current_state = ctx.board_module.getChessState()
            expected_state = ctx.chess_board_to_state_fn(ctx.chess_board)
            if current_state is not None and expected_state is not None:
                ctx.provide_correction_guidance_fn(current_state, expected_state)
            return

    # Check for "piece with no legal moves" on LIFT events
    # ANY piece lifted without valid moves should trigger correction mode - not just
    # the current player's piece. This handles:
    # - Current player lifting a blocked/pinned piece
    # - Player lifting opponent's piece (which has no legal moves since it's not their turn)
    # - Lifting an empty square (piece_color is None, handled separately)
    if is_lift and piece_color is not None:
        # Check if this piece has any legal moves from this square
        has_legal_moves = any(move.from_square == field for move in ctx.chess_board.legal_moves)
        if not has_legal_moves:
            log.warning(
                f"[GameManager.receive_field] Piece at {chess.square_name(field)} has no legal moves - "
                "entering correction mode"
            )
            ctx.board_module.beep(ctx.board_module.SOUND_WRONG_MOVE, event_type="error")
            ctx.enter_correction_mode_fn()
            current_state = ctx.board_module.getChessState()
            expected_state = ctx.chess_board_to_state_fn(ctx.chess_board)
            if current_state is not None and expected_state is not None:
                ctx.provide_correction_guidance_fn(current_state, expected_state)
            return

    # Forward to player manager (after board state validation to avoid incorrect move formation)
    ctx.on_piece_event_fn("lift" if is_lift else "place", field, ctx.chess_board)

    # Handle king-lift resign (board-level concern)
    if is_lift:
        ctx.handle_king_lift_resign_fn(field, piece_color)
        return

    # Cancel king-lift resign timer on any piece placement
    if ctx.move_state.king_lift_timer is not None:
        ctx.move_state._cancel_king_lift_timer()
        log.debug("[GameManager._process_field_event] Cancelled king-lift resign timer on PLACE")

        if ctx.get_king_lift_resign_menu_active_fn():
            log.info("[GameManager._process_field_event] King placed - cancelling resign menu")
            ctx.set_king_lift_resign_menu_active_fn(False)
            if ctx.on_king_lift_resign_cancel_fn:
                ctx.on_king_lift_resign_cancel_fn()

        ctx.move_state.king_lifted_square = INVALID_SQUARE
        ctx.move_state.king_lifted_color = None


__all__ = ["FieldEventContext", "process_field_event"]


