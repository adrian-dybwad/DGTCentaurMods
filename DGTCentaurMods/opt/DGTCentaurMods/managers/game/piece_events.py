"""Piece event handlers for GameManager (LIFT/PLACE).

This module extracts the high-branching physical-board piece event logic out of
`GameManager` to reduce file size and improve cohesion.

The logic is intentionally kept behavior-identical and uses dependency injection
for GameManager-owned callbacks/flags.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import chess

from DGTCentaurMods.board.logging import log

from .move_state import (
    BOARD_WIDTH,
    INVALID_SQUARE,
    MIN_UCI_MOVE_LENGTH,
    MoveState,
    PROMOTION_ROW_BLACK,
    PROMOTION_ROW_WHITE,
)


BOARD_SIZE = 64


@dataclass(frozen=True)
class PieceEventContext:
    """Dependencies required to process physical piece events."""

    chess_board: chess.Board
    game_state: object
    move_state: MoveState
    correction_mode: object
    player_manager: object
    board_module: object

    # GameManager helper callbacks
    get_expected_state_fn: Callable[[], Optional[bytearray]]
    enter_correction_mode_fn: Callable[[], None]
    provide_correction_guidance_fn: Callable[[Optional[bytearray], Optional[bytearray]], None]
    check_takeback_fn: Callable[[], bool]
    execute_move_fn: Callable[[int], None]
    execute_late_castling_fn: Callable[[int], None]

    # King-lift resign menu state
    get_king_lift_resign_menu_active_fn: Callable[[], bool]
    set_king_lift_resign_menu_active_fn: Callable[[bool], None]
    on_king_lift_resign_fn: Optional[Callable[[chess.Color], None]]
    on_king_lift_resign_cancel_fn: Optional[Callable[[], None]]


def handle_piece_lift(ctx: PieceEventContext, field: int, piece_color) -> None:
    """Handle piece lift event (piece_event==0)."""
    is_current_player_piece = (ctx.chess_board.turn == chess.WHITE) == (piece_color is True)

    # Late castling attempt: king lifted after rook was moved to castling destination as a regular move.
    if ctx.move_state.castling_rook_placed:
        expected_king_square = None
        expected_king_color = None
        if ctx.move_state.castling_rook_source in (MoveState.WHITE_KINGSIDE_ROOK, MoveState.WHITE_QUEENSIDE_ROOK):
            expected_king_square = MoveState.WHITE_KING_SQUARE
            expected_king_color = chess.WHITE
        elif ctx.move_state.castling_rook_source in (MoveState.BLACK_KINGSIDE_ROOK, MoveState.BLACK_QUEENSIDE_ROOK):
            expected_king_square = MoveState.BLACK_KING_SQUARE
            expected_king_color = chess.BLACK

        if field == expected_king_square:
            piece_at_field = ctx.chess_board.piece_at(field)
            is_correct_king = (
                piece_at_field is not None
                and piece_at_field.piece_type == chess.KING
                and piece_at_field.color == expected_king_color
            )
            if is_correct_king:
                log.info(
                    "[GameManager._handle_piece_lift] Late castling detected - "
                    f"king lifted from {chess.square_name(field)} after rook move"
                )
                ctx.move_state.source_square = field
                ctx.move_state.source_piece_color = piece_color
                ctx.move_state.late_castling_in_progress = True  # suppress board validation

                king_dest = None
                if ctx.move_state.castling_rook_source == MoveState.WHITE_KINGSIDE_ROOK:
                    king_dest = MoveState.WHITE_KINGSIDE_KING_DEST
                elif ctx.move_state.castling_rook_source == MoveState.WHITE_QUEENSIDE_ROOK:
                    king_dest = MoveState.WHITE_QUEENSIDE_KING_DEST
                elif ctx.move_state.castling_rook_source == MoveState.BLACK_KINGSIDE_ROOK:
                    king_dest = MoveState.BLACK_KINGSIDE_KING_DEST
                elif ctx.move_state.castling_rook_source == MoveState.BLACK_QUEENSIDE_ROOK:
                    king_dest = MoveState.BLACK_QUEENSIDE_KING_DEST

                ctx.move_state.legal_destination_squares = [field, king_dest] if king_dest else [field]
                return

        # If a different piece is lifted by the current player before a move starts, abandon late castling.
        if not is_current_player_piece:
            pass
        elif ctx.move_state.source_square < 0:
            log.info(
                "[GameManager._handle_piece_lift] Late castling abandoned - "
                f"different piece lifted from {chess.square_name(field)}"
            )
            ctx.move_state.castling_rook_source = INVALID_SQUARE
            ctx.move_state.castling_rook_placed = False
            ctx.move_state.late_castling_in_progress = False

    # Rook lift from castling square tracking (rook-first / late castling).
    if is_current_player_piece and ctx.move_state.source_square < 0:
        piece_at_field = ctx.chess_board.piece_at(field)
        if piece_at_field is not None and piece_at_field.piece_type == chess.ROOK:
            if ctx.move_state.is_rook_castling_square(field):
                castling_move = None
                if field == MoveState.WHITE_KINGSIDE_ROOK:
                    castling_move = chess.Move.from_uci("e1g1")
                elif field == MoveState.WHITE_QUEENSIDE_ROOK:
                    castling_move = chess.Move.from_uci("e1c1")
                elif field == MoveState.BLACK_KINGSIDE_ROOK:
                    castling_move = chess.Move.from_uci("e8g8")
                elif field == MoveState.BLACK_QUEENSIDE_ROOK:
                    castling_move = chess.Move.from_uci("e8c8")

                can_castle = castling_move is not None and castling_move in ctx.chess_board.legal_moves
                if can_castle:
                    log.info(
                        "[GameManager._handle_piece_lift] Potential castling rook lifted from "
                        f"{chess.square_name(field)}"
                    )
                    ctx.move_state.castling_rook_source = field
                    ctx.move_state.source_piece_color = piece_color

    # Track opposing side lifts
    if not is_current_player_piece:
        ctx.move_state.opponent_source_square = field

    # King-lift resign detection (same behavior as prior inline).
    piece_at_field = ctx.chess_board.piece_at(field)
    if piece_at_field is not None and piece_at_field.piece_type == chess.KING:
        king_color = piece_at_field.color

        can_resign_this_king = True
        if ctx.player_manager:
            player = ctx.player_manager.get_player(king_color)
            can_resign_this_king = player.can_resign()

        if can_resign_this_king:
            ctx.move_state._cancel_king_lift_timer()
            ctx.move_state.king_lifted_square = field
            ctx.move_state.king_lifted_color = king_color

            def _king_lift_timeout():
                log.info(
                    "[GameManager] King held off board for 3 seconds - showing resign menu for "
                    f"{'White' if king_color == chess.WHITE else 'Black'}"
                )
                ctx.set_king_lift_resign_menu_active_fn(True)
                if ctx.on_king_lift_resign_fn:
                    ctx.on_king_lift_resign_fn(king_color)

            ctx.move_state.king_lift_timer = threading.Timer(3.0, _king_lift_timeout)
            ctx.move_state.king_lift_timer.daemon = True
            ctx.move_state.king_lift_timer.start()
            log.debug(
                f"[GameManager._handle_piece_lift] King lifted from {chess.square_name(field)}, "
                "started 3-second resign timer"
            )

    # Move construction for current player pieces.
    if ctx.move_state.castling_rook_source == INVALID_SQUARE:
        if (
            field not in ctx.move_state.legal_destination_squares
            and ctx.move_state.source_square < 0
            and is_current_player_piece
        ):
            ctx.move_state.legal_destination_squares = ctx.game_state.get_legal_destinations(field)
            ctx.move_state.source_square = field
            ctx.move_state.source_piece_color = piece_color


def handle_piece_place(ctx: PieceEventContext, field: int, piece_color) -> None:
    """Handle piece place event (piece_event==1)."""
    # Cancel king-lift resign timer on any piece placement
    if ctx.move_state.king_lift_timer is not None:
        ctx.move_state._cancel_king_lift_timer()
        log.debug("[GameManager._handle_piece_place] Cancelled king-lift resign timer")

        if ctx.get_king_lift_resign_menu_active_fn():
            log.info("[GameManager._handle_piece_place] King placed - cancelling resign menu")
            ctx.set_king_lift_resign_menu_active_fn(False)
            if ctx.on_king_lift_resign_cancel_fn:
                ctx.on_king_lift_resign_cancel_fn()

        ctx.move_state.king_lifted_square = INVALID_SQUARE
        ctx.move_state.king_lifted_color = None

    # Priority: late castling completion first.
    if ctx.move_state.late_castling_in_progress:
        expected_king_dest = None
        if ctx.move_state.castling_rook_source == MoveState.WHITE_KINGSIDE_ROOK:
            expected_king_dest = MoveState.WHITE_KINGSIDE_KING_DEST
        elif ctx.move_state.castling_rook_source == MoveState.WHITE_QUEENSIDE_ROOK:
            expected_king_dest = MoveState.WHITE_QUEENSIDE_KING_DEST
        elif ctx.move_state.castling_rook_source == MoveState.BLACK_KINGSIDE_ROOK:
            expected_king_dest = MoveState.BLACK_KINGSIDE_KING_DEST
        elif ctx.move_state.castling_rook_source == MoveState.BLACK_QUEENSIDE_ROOK:
            expected_king_dest = MoveState.BLACK_QUEENSIDE_KING_DEST

        if expected_king_dest is not None and field == expected_king_dest:
            log.info(
                "[GameManager._handle_piece_place] Late castling completion: "
                f"King placed on {chess.square_name(field)}"
            )
            ctx.execute_late_castling_fn(ctx.move_state.castling_rook_source)
            return
        elif field == ctx.move_state.source_square:
            log.info(
                "[GameManager._handle_piece_place] Late castling cancelled: "
                f"King returned to {chess.square_name(field)}"
            )
            ctx.move_state.reset()
            ctx.board_module.ledsOff()
            return
        else:
            log.warning(
                "[GameManager._handle_piece_place] Late castling failed: "
                f"King placed on unexpected square {chess.square_name(field)}"
            )
            ctx.board_module.beep(ctx.board_module.SOUND_WRONG_MOVE, event_type="error")
            ctx.enter_correction_mode_fn()
            current_state = ctx.board_module.getChessState()
            expected_state = ctx.get_expected_state_fn()
            if expected_state is not None:
                ctx.provide_correction_guidance_fn(current_state, expected_state)
            ctx.move_state.reset()
            return

    is_current_player_piece = (ctx.chess_board.turn == chess.WHITE) == (piece_color is True)

    # Handle opponent piece placed back
    if (
        (not is_current_player_piece)
        and ctx.move_state.opponent_source_square >= 0
        and field == ctx.move_state.opponent_source_square
    ):
        ctx.board_module.ledsOff()
        ctx.move_state.opponent_source_square = INVALID_SQUARE
        return

    # Rook moved from castling square: treat as regular rook move and track for late castling.
    if ctx.move_state.castling_rook_source != INVALID_SQUARE and ctx.move_state.source_square < 0:
        if field == ctx.move_state.castling_rook_source:
            log.info(
                "[GameManager._handle_piece_place] Rook returned to "
                f"{chess.square_name(field)} - cancelling potential castling"
            )
            ctx.move_state.castling_rook_source = INVALID_SQUARE
            ctx.move_state.castling_rook_placed = False
            return

        ctx.move_state.source_square = ctx.move_state.castling_rook_source
        ctx.move_state.legal_destination_squares = ctx.game_state.get_legal_destinations(
            ctx.move_state.castling_rook_source
        )

        if ctx.move_state.is_valid_rook_castling_destination(ctx.move_state.castling_rook_source, field):
            log.info(
                "[GameManager._handle_piece_place] Rook moved to castling position "
                f"{chess.square_name(field)} - treating as regular move, tracking for late castling"
            )
            ctx.move_state.castling_rook_placed = True
        else:
            ctx.move_state.castling_rook_source = INVALID_SQUARE
            ctx.move_state.castling_rook_placed = False

    # Ignore stale PLACE events without corresponding LIFT
    if ctx.move_state.source_square < 0 and ctx.move_state.opponent_source_square < 0:
        current_state = ctx.board_module.getChessState()
        expected_state = ctx.get_expected_state_fn()

        if current_state is not None and expected_state is not None:
            extra_squares = []
            if len(current_state) == BOARD_SIZE and len(expected_state) == BOARD_SIZE:
                for i in range(BOARD_SIZE):
                    if expected_state[i] == 0 and current_state[i] == 1:
                        extra_squares.append(i)
                if extra_squares:
                    log.debug(f"[GameManager._handle_piece_place] Current FEN: {ctx.chess_board.fen()}")
                    log.debug(
                        "[GameManager._handle_piece_place] Extra pieces detected: "
                        f"{[chess.square_name(sq) for sq in extra_squares]}"
                    )

            if extra_squares:
                log.warning(
                    "[GameManager._handle_piece_place] PLACE event without LIFT created invalid board state with "
                    f"{len(extra_squares)} extra piece(s) at {[chess.square_name(sq) for sq in extra_squares]}, "
                    "entering correction mode"
                )
                ctx.board_module.beep(ctx.board_module.SOUND_WRONG_MOVE, event_type="error")
                ctx.enter_correction_mode_fn()
                ctx.provide_correction_guidance_fn(current_state, expected_state)
                return
        else:
            log.debug(
                "[GameManager._handle_piece_place] Cannot check board state: "
                f"current_state={current_state is not None}, expected_state={expected_state is not None}"
            )

        if getattr(ctx.correction_mode, "just_exited", False):
            if ctx.move_state.is_forced_move and ctx.move_state.computer_move_uci:
                if len(ctx.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                    forced_source = chess.parse_square(ctx.move_state.computer_move_uci[0:2])
                    if field != forced_source:
                        log.info(
                            "[GameManager._handle_piece_place] Ignoring stale PLACE event after correction exit for "
                            f"field {field}"
                        )
                        ctx.correction_mode.clear_exit_flag()
                        return
            else:
                log.info(
                    "[GameManager._handle_piece_place] Ignoring stale PLACE event after correction exit for "
                    f"field {field}"
                )
                ctx.correction_mode.clear_exit_flag()
                return

        if ctx.move_state.is_forced_move and ctx.move_state.computer_move_uci:
            if len(ctx.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH:
                forced_source = chess.parse_square(ctx.move_state.computer_move_uci[0:2])
                if field == forced_source:
                    log.info(
                        "[GameManager._handle_piece_place] Ignoring stale PLACE event for forced move source field "
                        f"{field}"
                    )
                    ctx.correction_mode.clear_exit_flag()
                    return

        if not ctx.move_state.is_forced_move:
            log.info(f"[GameManager._handle_piece_place] Ignoring stale PLACE event for field {field}")
            ctx.correction_mode.clear_exit_flag()
            return

    # Illegal placement
    if field not in ctx.move_state.legal_destination_squares:
        ctx.board_module.beep(ctx.board_module.SOUND_WRONG_MOVE, event_type="error")
        log.warning(f"[GameManager._handle_piece_place] Piece placed on illegal square {field}")
        is_takeback = ctx.check_takeback_fn()
        if not is_takeback:
            ctx.enter_correction_mode_fn()
            current_state = ctx.board_module.getChessState()
            expected_state = ctx.get_expected_state_fn()
            if expected_state is not None:
                ctx.provide_correction_guidance_fn(current_state, expected_state)
        return

    # Legal placement
    if field == ctx.move_state.source_square:
        ctx.board_module.ledsOff()
        ctx.move_state.source_square = INVALID_SQUARE
        ctx.move_state.legal_destination_squares = []
        ctx.move_state.source_piece_color = None
        ctx.move_state.castling_rook_source = INVALID_SQUARE
        ctx.move_state.castling_rook_placed = False
    else:
        ctx.execute_move_fn(field)


__all__ = ["PieceEventContext", "handle_piece_lift", "handle_piece_place"]


