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

from universalchess.board.logging import log
from universalchess.utils.led import LedCallbacks

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
    led: LedCallbacks  # LED control callbacks

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
            legal_destinations = ctx.game_state.get_legal_destinations(field)
            
            # If piece has no legal moves, enter correction mode immediately
            if not legal_destinations:
                log.warning(
                    f"[GameManager._handle_piece_lift] Piece at {chess.square_name(field)} has no legal moves - "
                    "entering correction mode"
                )
                ctx.board_module.beep(ctx.board_module.SOUND_WRONG_MOVE, event_type="error")
                ctx.enter_correction_mode_fn()
                current_state = ctx.board_module.getChessState()
                expected_state = ctx.get_expected_state_fn()
                if current_state is not None and expected_state is not None:
                    ctx.provide_correction_guidance_fn(current_state, expected_state)
                return
            
            ctx.move_state.legal_destination_squares = legal_destinations
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
            ctx.led.off()
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

    # Forced-move "missed lift" recovery:
    # Some boards can occasionally miss the LIFT event. When the game is waiting on a forced
    # computer move (engine/Lichess opponent), the player may complete the move physically
    # but only a PLACE is observed. In that case, accept the move if the *full* physical
    # occupancy exactly matches the expected post-move occupancy computed by applying the
    # forced move to the current logical board (supports captures and castling).
    if (
        ctx.move_state.is_forced_move
        and ctx.move_state.source_square < 0
        and isinstance(ctx.move_state.computer_move_uci, str)
        and len(ctx.move_state.computer_move_uci) >= MIN_UCI_MOVE_LENGTH
    ):
        forced_uci = ctx.move_state.computer_move_uci
        try:
            forced_source = chess.parse_square(forced_uci[0:2])
            forced_dest = chess.parse_square(forced_uci[2:4])
        except ValueError:
            forced_source = None
            forced_dest = None

        if forced_source is not None and forced_dest is not None:
            current_state = ctx.board_module.getChessState()
            if current_state is not None and len(current_state) == BOARD_SIZE:
                # Compute expected post-move occupancy by applying the forced move on a board copy.
                expected_after: Optional[bytearray] = None
                forced_move_for_apply = forced_uci

                # Promotion robustness: if forced UCI is missing the promotion piece, default to queen,
                # mirroring the behavior in move execution for forced moves.
                if len(forced_move_for_apply) == 4:
                    piece_at_source = ctx.chess_board.piece_at(forced_source)
                    if piece_at_source is not None and piece_at_source.piece_type == chess.PAWN:
                        promotion_rank = 7 if piece_at_source.color == chess.WHITE else 0
                        if (forced_dest // BOARD_WIDTH) == promotion_rank:
                            forced_move_for_apply = forced_move_for_apply + "q"

                try:
                    board_copy = ctx.chess_board.copy(stack=False)
                    board_copy.push_uci(forced_move_for_apply)
                    expected_after = bytearray(BOARD_SIZE)
                    for sq in range(BOARD_SIZE):
                        expected_after[sq] = 1 if board_copy.piece_at(sq) is not None else 0
                except Exception as e:
                    log.debug(
                        "[GameManager._handle_piece_place] Forced-move recovery could not compute expected_after "
                        f"for uci={forced_move_for_apply}: {e}"
                    )

                if expected_after is not None and expected_after == current_state:
                    # Optional guard: require that the observed PLACE is on the forced destination, except
                    # for castling where either destination square might be the last observed PLACE.
                    allow_accept = False
                    if forced_uci in ("e1g1", "e1c1", "e8g8", "e8c8"):
                        # Castling: accept completion if board matches expected_after and PLACE is on either moved piece destination.
                        if forced_uci == "e1g1":
                            allow_accept = field in (chess.G1, chess.F1)
                        elif forced_uci == "e1c1":
                            allow_accept = field in (chess.C1, chess.D1)
                        elif forced_uci == "e8g8":
                            allow_accept = field in (chess.G8, chess.F8)
                        elif forced_uci == "e8c8":
                            allow_accept = field in (chess.C8, chess.D8)
                    else:
                        allow_accept = field == forced_dest

                    if allow_accept:
                        log.info(
                            "[GameManager._handle_piece_place] MISSED LIFT RECOVERY (forced move): "
                            f"physical occupancy matches forced move {forced_uci}, observed PLACE on {chess.square_name(field)}"
                        )
                        ctx.move_state.source_square = forced_source
                        ctx.move_state.source_piece_color = piece_color
                        ctx.move_state.legal_destination_squares = [forced_source, forced_dest]
                        ctx.execute_move_fn(field)
                        return

    # Handle opponent piece placed back
    if (
        (not is_current_player_piece)
        and ctx.move_state.opponent_source_square >= 0
        and field == ctx.move_state.opponent_source_square
    ):
        ctx.led.off()
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
        ctx.led.off()
        ctx.move_state.source_square = INVALID_SQUARE
        ctx.move_state.legal_destination_squares = []
        ctx.move_state.source_piece_color = None
        ctx.move_state.castling_rook_source = INVALID_SQUARE
        ctx.move_state.castling_rook_placed = False
    else:
        ctx.execute_move_fn(field)


__all__ = ["PieceEventContext", "handle_piece_lift", "handle_piece_place"]


