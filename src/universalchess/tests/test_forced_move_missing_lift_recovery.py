import chess
from unittest.mock import Mock

from universalchess.managers.game.move_state import MoveState
from universalchess.managers.game.piece_events import PieceEventContext, handle_piece_place


def _piece_presence_state(board: chess.Board) -> bytearray:
    state = bytearray(64)
    for sq in chess.SQUARES:
        state[sq] = 1 if board.piece_at(sq) is not None else 0
    return state


class _CorrectionModeStub:
    just_exited = False

    def clear_exit_flag(self) -> None:
        return


class _GameStateStub:
    def get_legal_destinations(self, _field: int):
        return []


def test_forced_move_place_only_recovers_when_occupancy_matches_post_move_state() -> None:
    # Expected failure message if broken: "execute_move_fn not called for PLACE-only forced move recovery"
    # Why: When LIFT is missed during a forced move, recovery should accept the move if the board occupancy matches.
    chess_board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1")
    move_state = MoveState()
    assert move_state.set_computer_move("g8f6", forced=True)

    expected_before = _piece_presence_state(chess_board)
    expected_after = bytearray(expected_before)
    expected_after[chess.G8] = 0
    expected_after[chess.F6] = 1

    board_module = Mock()
    board_module.getChessState.return_value = expected_after
    board_module.beep = Mock()
    led = Mock()
    led.off = Mock()

    execute_move_fn = Mock()
    enter_correction_mode_fn = Mock()
    provide_correction_guidance_fn = Mock()

    ctx = PieceEventContext(
        chess_board=chess_board,
        game_state=_GameStateStub(),
        move_state=move_state,
        correction_mode=_CorrectionModeStub(),
        player_manager=None,
        board_module=board_module,
        led=led,
        get_expected_state_fn=lambda: expected_before,
        enter_correction_mode_fn=enter_correction_mode_fn,
        provide_correction_guidance_fn=provide_correction_guidance_fn,
        check_takeback_fn=lambda: False,
        execute_move_fn=execute_move_fn,
        execute_late_castling_fn=Mock(),
        get_king_lift_resign_menu_active_fn=lambda: False,
        set_king_lift_resign_menu_active_fn=lambda _v: None,
        on_king_lift_resign_fn=None,
        on_king_lift_resign_cancel_fn=None,
    )

    handle_piece_place(ctx, chess.F6, chess.BLACK)

    execute_move_fn.assert_called_once_with(chess.F6)
    enter_correction_mode_fn.assert_not_called()


def test_forced_move_place_only_does_not_recover_when_occupancy_does_not_match_post_move_state() -> None:
    # Expected failure message if broken: "enter_correction_mode_fn not called when occupancy mismatch"
    # Why: Recovery must not accept PLACE-only events unless the physical board matches expected post-move occupancy.
    chess_board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1")
    move_state = MoveState()
    assert move_state.set_computer_move("g8f6", forced=True)

    expected_before = _piece_presence_state(chess_board)
    bad_current_state = bytearray(expected_before)
    # Destination occupied but source still occupied -> not a valid completion of the forced move.
    bad_current_state[chess.F6] = 1
    bad_current_state[chess.G8] = 1

    board_module = Mock()
    board_module.getChessState.return_value = bad_current_state
    board_module.beep = Mock()
    led = Mock()
    led.off = Mock()

    execute_move_fn = Mock()
    enter_correction_mode_fn = Mock()
    provide_correction_guidance_fn = Mock()

    ctx = PieceEventContext(
        chess_board=chess_board,
        game_state=_GameStateStub(),
        move_state=move_state,
        correction_mode=_CorrectionModeStub(),
        player_manager=None,
        board_module=board_module,
        led=led,
        get_expected_state_fn=lambda: expected_before,
        enter_correction_mode_fn=enter_correction_mode_fn,
        provide_correction_guidance_fn=provide_correction_guidance_fn,
        check_takeback_fn=lambda: False,
        execute_move_fn=execute_move_fn,
        execute_late_castling_fn=Mock(),
        get_king_lift_resign_menu_active_fn=lambda: False,
        set_king_lift_resign_menu_active_fn=lambda _v: None,
        on_king_lift_resign_fn=None,
        on_king_lift_resign_cancel_fn=None,
    )

    handle_piece_place(ctx, chess.F6, chess.BLACK)

    enter_correction_mode_fn.assert_called()
    execute_move_fn.assert_not_called()


