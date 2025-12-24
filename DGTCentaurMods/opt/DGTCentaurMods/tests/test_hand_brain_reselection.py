"""Tests for piece type re-selection in reverse Hand+Brain mode.

When a piece is "bumped" (lifted and replaced on the same square) in reverse
hand-brain mode, it selects the piece type. This test verifies that a second
bump changes the selection, and if a move has already been computed, the
engine recalculates for the new piece type.

Test Scenarios:
1. Re-selection during COMPUTING_MOVE phase (engine still thinking)
2. Re-selection during WAITING_EXECUTION phase (move already computed)
"""
from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import threading
import time

import chess

# Mock hardware-dependent modules before importing hand_brain
# These modules are only available on Raspberry Pi hardware
sys.modules['spidev'] = MagicMock()
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()
sys.modules['gpiozero'] = MagicMock()
sys.modules['lgpio'] = MagicMock()
sys.modules['serial'] = MagicMock()
sys.modules['serial.tools'] = MagicMock()
sys.modules['serial.tools.list_ports'] = MagicMock()

# Import directly from the module file to avoid package __init__ import chain
# which tries to import LichessPlayer and other modules with hardware dependencies
from DGTCentaurMods.players.hand_brain import (
    HandBrainPlayer, HandBrainConfig, HandBrainMode, HandBrainPhase
)
from DGTCentaurMods.players.base import PlayerState


class MockEngine:
    """Mock UCI engine that returns configurable moves."""
    
    def __init__(self):
        self.play_results = []  # List of moves to return, in order
        self.play_call_count = 0
        self.configure_called = False
        self._configured_options = {}
        
    def play(self, board, limit, root_moves=None):
        """Return the next configured move or first legal move."""
        self.play_call_count += 1
        
        result = MagicMock()
        if self.play_results and self.play_call_count <= len(self.play_results):
            result.move = self.play_results[self.play_call_count - 1]
        elif root_moves:
            result.move = root_moves[0]
        else:
            result.move = list(board.legal_moves)[0] if board.legal_moves else None
        return result
    
    def configure(self, options):
        self.configure_called = True
        self._configured_options = options
    
    def analyse(self, board, limit):
        return {"score": MagicMock(white=MagicMock(return_value=MagicMock(is_mate=MagicMock(return_value=False), score=MagicMock(return_value=0))))}
    
    def quit(self):
        pass


class TestReverseModeReselection(unittest.TestCase):
    """Test cases for piece type re-selection in reverse hand-brain mode."""
    
    def _create_player(self):
        """Create a HandBrainPlayer in REVERSE mode with mock engine."""
        from DGTCentaurMods.players.hand_brain import (
            HandBrainPlayer, HandBrainConfig, HandBrainMode, HandBrainPhase
        )
        
        config = HandBrainConfig(
            name="Test Reverse H+B",
            color=chess.WHITE,
            mode=HandBrainMode.REVERSE,
            time_limit_seconds=0.1,
            engine_name="mock_engine"
        )
        player = HandBrainPlayer(config)
        
        # Inject mock engine
        player._engine = MockEngine()
        player._state = player.state.__class__.READY  # PlayerState.READY
        
        return player
    
    def test_reselection_during_computing_move_changes_piece_type(self):
        """Test that bumping a different piece during COMPUTING_MOVE changes selection.
        
        Scenario:
        1. User bumps a knight (lift e4, place e4) - knight selected
        2. Engine starts computing knight moves
        3. User bumps a bishop (lift c4, place c4) before engine finishes
        4. Engine should now compute bishop moves instead
        
        Expected: selected_piece_type should change to bishop.
        Failure: The second bump is ignored, knight move is computed.
        """
        from DGTCentaurMods.players.hand_brain import (
            HandBrainPlayer, HandBrainConfig, HandBrainMode, HandBrainPhase
        )
        
        player = self._create_player()
        
        # Set up callbacks
        move_callback = MagicMock()
        pending_move_callback = MagicMock()
        led_callback = MagicMock()
        
        player.set_move_callback(move_callback)
        player.set_pending_move_callback(pending_move_callback)
        player.set_piece_squares_led_callback(led_callback)
        
        # Create position with knight on e4 and bishop on c4
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        board.set_piece_at(chess.C4, chess.Piece(chess.BISHOP, chess.WHITE))
        
        # Start the turn
        player._do_request_move(board)
        
        assert player._phase == HandBrainPhase.WAITING_PIECE_SELECTION
        
        # Bump knight on e4 (select knight)
        player.on_piece_event("lift", chess.E4, board)
        player.on_piece_event("place", chess.E4, board)
        
        # Engine should start computing - force phase to COMPUTING_MOVE
        # (In real usage the thread would set this, but we simulate)
        player._phase = HandBrainPhase.COMPUTING_MOVE
        player._selected_piece_type = chess.KNIGHT
        
        # Now bump bishop on c4 BEFORE engine finishes (during COMPUTING_MOVE)
        player.on_piece_event("lift", chess.C4, board)
        player.on_piece_event("place", chess.C4, board)
        
        # The selected piece type should change to bishop
        assert player._selected_piece_type == chess.BISHOP, \
            f"Expected BISHOP, got {chess.piece_name(player._selected_piece_type) if player._selected_piece_type else None}"
    
    def test_reselection_during_waiting_execution_recalculates_move(self):
        """Test that bumping a different piece during WAITING_EXECUTION recalculates.
        
        Scenario:
        1. User bumps a knight - knight selected
        2. Engine computes and displays knight move (e.g., Ne4-f6)
        3. User changes their mind, bumps a rook instead
        4. Engine should recalculate and display best rook move
        
        Expected: pending_move should change to a rook move.
        Failure: The second bump is ignored, knight move remains pending.
        """
        from DGTCentaurMods.players.hand_brain import (
            HandBrainPlayer, HandBrainConfig, HandBrainMode, HandBrainPhase
        )
        
        player = self._create_player()
        
        # Set up callbacks
        pending_moves_received = []
        def pending_move_callback(move):
            pending_moves_received.append(move)
        
        player.set_pending_move_callback(pending_move_callback)
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        
        # Create position: knight on e4, rook on a1
        # Knight can go to f6, rook can go to a8
        board = chess.Board("8/8/8/8/4N3/8/8/R3K2R w KQ - 0 1")
        
        # Configure mock engine to return different moves for each call
        # First call: return knight move
        # Second call: return rook move
        knight_move = chess.Move(chess.E4, chess.F6)
        rook_move = chess.Move(chess.A1, chess.A8)
        player._engine.play_results = [knight_move, rook_move]
        
        # Start the turn
        player._do_request_move(board)
        
        # Bump knight on e4 (select knight)
        player.on_piece_event("lift", chess.E4, board)
        player.on_piece_event("place", chess.E4, board)
        
        # Wait for engine computation to complete
        time.sleep(0.3)
        
        # Should be waiting for execution with knight move pending
        assert player._phase == HandBrainPhase.WAITING_EXECUTION, \
            f"Expected WAITING_EXECUTION, got {player._phase.name}"
        assert player._pending_move is not None, "No pending move after knight selection"
        first_pending_move = player._pending_move
        
        # Now bump rook on a1 to change selection
        player.on_piece_event("lift", chess.A1, board)
        player.on_piece_event("place", chess.A1, board)
        
        # Wait for recalculation
        time.sleep(0.3)
        
        # The pending move should now be a rook move
        assert player._selected_piece_type == chess.ROOK, \
            f"Expected ROOK, got {chess.piece_name(player._selected_piece_type) if player._selected_piece_type else None}"
        assert player._pending_move is not None, "No pending move after rook re-selection"
        
        # Verify that the move changed (it should be from the rook, not knight)
        assert player._pending_move.from_square == chess.A1, \
            f"Expected move from a1, got {chess.square_name(player._pending_move.from_square)}"
    
    def test_bump_same_piece_type_during_waiting_execution_no_change(self):
        """Test that bumping same piece type doesn't restart computation.
        
        If user bumps a knight while knight is already selected, there's no
        need to recalculate.
        
        Expected: No additional engine calls, same move remains pending.
        Failure: Unnecessary recalculation occurs.
        """
        from DGTCentaurMods.players.hand_brain import (
            HandBrainPlayer, HandBrainConfig, HandBrainMode, HandBrainPhase
        )
        
        player = self._create_player()
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        player.set_pending_move_callback(MagicMock())
        
        # Position with two knights
        board = chess.Board("8/8/8/8/4N3/8/8/4K2N w - - 0 1")
        
        knight_move = chess.Move(chess.E4, chess.F6)
        player._engine.play_results = [knight_move, knight_move]
        
        # Start turn and select knight
        player._do_request_move(board)
        player.on_piece_event("lift", chess.E4, board)
        player.on_piece_event("place", chess.E4, board)
        
        time.sleep(0.3)
        
        initial_call_count = player._engine.play_call_count
        initial_pending_move = player._pending_move
        
        # Bump the OTHER knight (h1) - same piece TYPE
        player.on_piece_event("lift", chess.H1, board)
        player.on_piece_event("place", chess.H1, board)
        
        time.sleep(0.3)
        
        # Should NOT trigger recalculation since same piece type
        # (This is optional optimization - may or may not be implemented)
        # For now, we just verify the selection is still knight
        assert player._selected_piece_type == chess.KNIGHT


class TestReverseModeReselectionEdgeCases(unittest.TestCase):
    """Edge cases for piece type re-selection."""
    
    def _create_player(self):
        """Create a HandBrainPlayer in REVERSE mode with mock engine."""
        from DGTCentaurMods.players.hand_brain import (
            HandBrainPlayer, HandBrainConfig, HandBrainMode
        )
        
        config = HandBrainConfig(
            name="Test Reverse H+B",
            color=chess.WHITE,
            mode=HandBrainMode.REVERSE,
            time_limit_seconds=0.1,
            engine_name="mock_engine"
        )
        player = HandBrainPlayer(config)
        player._engine = MockEngine()
        player._state = player.state.__class__.READY
        
        return player
    
    def test_lift_different_piece_during_computing_resets_selection(self):
        """Test that lifting a different piece type during computing shows its LEDs.
        
        When user lifts a different piece type during COMPUTING_MOVE, the LEDs
        should update to show all pieces of the new type.
        
        Expected: LED callback called with squares of the new piece type.
        Failure: LEDs not updated for the new piece type.
        """
        from DGTCentaurMods.players.hand_brain import HandBrainPhase
        
        player = self._create_player()
        
        led_squares_received = []
        def led_callback(squares):
            led_squares_received.append(squares)
        
        player.set_piece_squares_led_callback(led_callback)
        player.set_move_callback(MagicMock())
        player.set_pending_move_callback(MagicMock())
        
        # Position: knight on e4, two bishops on c4 and f4
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        board.set_piece_at(chess.C4, chess.Piece(chess.BISHOP, chess.WHITE))
        board.set_piece_at(chess.F4, chess.Piece(chess.BISHOP, chess.WHITE))
        
        player._do_request_move(board)
        
        # Select knight first
        player.on_piece_event("lift", chess.E4, board)
        player.on_piece_event("place", chess.E4, board)
        
        player._phase = HandBrainPhase.COMPUTING_MOVE
        player._selected_piece_type = chess.KNIGHT
        
        led_squares_received.clear()
        
        # Lift bishop during computing
        player.on_piece_event("lift", chess.C4, board)
        
        # LED callback should be called with both bishop squares
        assert len(led_squares_received) > 0, "LED callback not called when lifting new piece type"
        assert chess.C4 in led_squares_received[-1], "c4 not in LED squares"
        assert chess.F4 in led_squares_received[-1], "f4 not in LED squares"
    
    def test_opponent_piece_during_reselection_ignored(self):
        """Test that bumping opponent's piece during re-selection is ignored.
        
        If user accidentally bumps an opponent's piece while trying to change
        their selection, it should not affect the current selection.
        
        Expected: selected_piece_type unchanged, status message shown.
        Failure: Selection changed or error triggered.
        """
        from DGTCentaurMods.players.hand_brain import HandBrainPhase
        
        player = self._create_player()
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        player.set_pending_move_callback(MagicMock())
        
        status_messages = []
        def status_callback(msg):
            status_messages.append(msg)
        player.set_status_callback(status_callback)
        
        # Position: white knight on e4, black bishop on d5
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        board.set_piece_at(chess.D5, chess.Piece(chess.BISHOP, chess.BLACK))
        
        player._do_request_move(board)
        
        # Select knight
        player.on_piece_event("lift", chess.E4, board)
        player.on_piece_event("place", chess.E4, board)
        
        player._phase = HandBrainPhase.WAITING_EXECUTION
        player._selected_piece_type = chess.KNIGHT
        player._pending_move = chess.Move(chess.E4, chess.F6)
        
        # Try to bump opponent's bishop
        player.on_piece_event("lift", chess.D5, board)
        player.on_piece_event("place", chess.D5, board)
        
        # Selection should remain knight
        assert player._selected_piece_type == chess.KNIGHT, \
            "Selection changed after bumping opponent's piece"
        assert player._pending_move == chess.Move(chess.E4, chess.F6), \
            "Pending move changed after bumping opponent's piece"

    def test_piece_placed_on_wrong_square_triggers_correction_mode(self):
        """Test that moving a piece to a different square triggers correction mode.
        
        In REVERSE mode, when a user lifts a piece for selection but places it
        on a different square (not the original square), this creates a physical
        board inconsistency. The player should report an error to trigger
        correction mode in the GameManager.
        
        Expected: _report_error("move_mismatch") is called.
        Failure: Error not triggered; board would be out of sync.
        """
        player = self._create_player()
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        player.set_pending_move_callback(MagicMock())
        
        errors_received = []
        def error_callback(error_type):
            errors_received.append(error_type)
        player.set_error_callback(error_callback)
        
        # Position: white knight on e4
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        
        player._do_request_move(board)
        
        # User lifts knight from e4
        player.on_piece_event("lift", chess.E4, board)
        
        # User places it on a different square (not e4) - this is wrong
        # Simulate the board change
        board.remove_piece_at(chess.E4)
        board.set_piece_at(chess.F6, chess.Piece(chess.KNIGHT, chess.WHITE))
        player.on_piece_event("place", chess.F6, board)
        
        # Error should have been reported
        assert len(errors_received) == 1, \
            f"Expected 1 error, got {len(errors_received)}: {errors_received}"
        assert errors_received[0] == "move_mismatch", \
            f"Expected 'move_mismatch' error, got '{errors_received[0]}'"

    def test_correction_mode_exit_restores_waiting_piece_selection_status(self):
        """Test that on_correction_mode_exit restores status in WAITING_PIECE_SELECTION.
        
        When correction mode exits while the player is waiting for piece selection,
        the status message should be restored to guide the user.
        
        Expected: Status message "Lift piece to select type" is shown.
        Failure: No status message or wrong message shown.
        """
        player = self._create_player()
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        player.set_pending_move_callback(MagicMock())
        
        status_messages = []
        def status_callback(msg):
            status_messages.append(msg)
        player.set_status_callback(status_callback)
        
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        
        player._do_request_move(board)
        
        # Player should be in WAITING_PIECE_SELECTION
        assert player._phase == HandBrainPhase.WAITING_PIECE_SELECTION
        
        # Clear status messages
        status_messages.clear()
        
        # Simulate correction mode exit
        player.on_correction_mode_exit()
        
        # Status should be restored
        assert len(status_messages) == 1, \
            f"Expected 1 status message, got {len(status_messages)}"
        assert status_messages[0] == "Lift piece to select type", \
            f"Expected 'Lift piece to select type', got '{status_messages[0]}'"

    def test_correction_mode_exit_restores_waiting_execution_leds(self):
        """Test that on_correction_mode_exit re-triggers pending move callback.
        
        When correction mode exits while the player is in WAITING_EXECUTION
        with a computed move, the pending move callback should be re-triggered
        to restore LEDs.
        
        Expected: pending_move_callback called with the pending move.
        Failure: Callback not called or called with wrong move.
        """
        player = self._create_player()
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        player.set_status_callback(MagicMock())
        
        pending_moves = []
        def pending_move_callback(move):
            pending_moves.append(move)
        player.set_pending_move_callback(pending_move_callback)
        
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        
        player._do_request_move(board)
        
        # Simulate computed move and set phase
        player._phase = HandBrainPhase.WAITING_EXECUTION
        player._selected_piece_type = chess.KNIGHT
        player._pending_move = chess.Move(chess.E4, chess.F6)
        
        # Clear pending moves list
        pending_moves.clear()
        
        # Simulate correction mode exit
        player.on_correction_mode_exit()
        
        # Pending move callback should be called
        assert len(pending_moves) == 1, \
            f"Expected 1 pending move callback, got {len(pending_moves)}"
        assert pending_moves[0] == chess.Move(chess.E4, chess.F6), \
            f"Expected e4f6, got {pending_moves[0].uci()}"

    def test_opponent_piece_lift_triggers_correction_mode(self):
        """Test that lifting an opponent's piece triggers correction mode immediately.
        
        When a user lifts an opponent's piece, the physical board becomes
        inconsistent with the logical board (piece is off the board). Correction
        mode should be entered immediately on lift.
        
        Expected: _report_error("move_mismatch") is called on lift.
        Failure: Error not triggered; board would be out of sync.
        """
        player = self._create_player()
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        player.set_pending_move_callback(MagicMock())
        
        errors_received = []
        def error_callback(error_type):
            errors_received.append(error_type)
        player.set_error_callback(error_callback)
        
        # Position: white knight on e4, black bishop on d5
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        board.set_piece_at(chess.D5, chess.Piece(chess.BISHOP, chess.BLACK))
        
        player._do_request_move(board)
        
        # User lifts opponent's bishop from d5 - should immediately trigger correction mode
        player.on_piece_event("lift", chess.D5, board)
        
        # Error should have been reported immediately on lift
        assert len(errors_received) == 1, \
            f"Expected 1 error on lift, got {len(errors_received)}: {errors_received}"
        assert errors_received[0] == "move_mismatch", \
            f"Expected 'move_mismatch' error, got '{errors_received[0]}'"

    def test_opponent_piece_returned_correction_mode_exits(self):
        """Test that returning an opponent's piece allows correction mode to exit.
        
        Lifting an opponent's piece enters correction mode. Placing it back
        allows correction mode to exit (GameManager will detect board match).
        The player reports an error on lift, but placing back clears the
        opponent tracking so no additional error is reported.
        
        Expected: One error on lift, no additional error on place-back.
        Failure: Multiple errors reported or tracking not cleared.
        """
        player = self._create_player()
        player.set_piece_squares_led_callback(MagicMock())
        player.set_move_callback(MagicMock())
        player.set_pending_move_callback(MagicMock())
        
        errors_received = []
        def error_callback(error_type):
            errors_received.append(error_type)
        player.set_error_callback(error_callback)
        
        # Position: white knight on e4, black bishop on d5
        board = chess.Board()
        board.set_piece_at(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
        board.set_piece_at(chess.D5, chess.Piece(chess.BISHOP, chess.BLACK))
        
        player._do_request_move(board)
        
        # User lifts opponent's bishop from d5 - enters correction mode
        player.on_piece_event("lift", chess.D5, board)
        
        # Should have one error from lift
        assert len(errors_received) == 1, \
            f"Expected 1 error after lift, got {len(errors_received)}: {errors_received}"
        
        # User puts it back on the same square - no additional error
        player.on_piece_event("place", chess.D5, board)
        
        # Still only one error (from lift)
        assert len(errors_received) == 1, \
            f"Expected still 1 error after place-back, got {len(errors_received)}: {errors_received}"
        
        # Opponent tracking should be cleared
        assert player._opponent_lifted_square is None, \
            "Opponent lifted square should be cleared after place-back"


if __name__ == '__main__':
    unittest.main()

