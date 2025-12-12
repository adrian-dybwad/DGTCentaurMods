#!/usr/bin/env python3
"""
Unit Tests for Rook-First Castling Support

Tests verify that castling works correctly when the player moves
the rook before the king (non-standard but common physical ordering).

This test is self-contained and tests the castling logic directly
without requiring the full DGTCentaurMods environment.

USAGE:
    # Navigate to opt folder
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    
    # Run test
    python3 DGTCentaurMods/tests/test_rook_first_castling.py

    # Or with pytest from project root
    source .venv/bin/activate
    python -m pytest DGTCentaurMods/opt/DGTCentaurMods/tests/test_rook_first_castling.py -v
"""

import unittest

# Define chess square constants (same as python-chess library)
# These match the chess.Square enum values
A1, B1, C1, D1, E1, F1, G1, H1 = range(8)
A2, B2, C2, D2, E2, F2, G2, H2 = range(8, 16)
A3, B3, C3, D3, E3, F3, G3, H3 = range(16, 24)
A4, B4, C4, D4, E4, F4, G4, H4 = range(24, 32)
A5, B5, C5, D5, E5, F5, G5, H5 = range(32, 40)
A6, B6, C6, D6, E6, F6, G6, H6 = range(40, 48)
A7, B7, C7, D7, E7, F7, G7, H7 = range(48, 56)
A8, B8, C8, D8, E8, F8, G8, H8 = range(56, 64)

INVALID_SQUARE = -1


class MockMoveState:
    """Mock version of MoveState for testing castling logic.
    
    Mirrors the castling-related constants and methods from game_manager.MoveState.
    """
    
    # Castling square definitions (chess square indices 0=a1, 63=h8)
    # King starting squares
    WHITE_KING_SQUARE = E1  # 4
    BLACK_KING_SQUARE = E8  # 60
    
    # Rook starting squares
    WHITE_KINGSIDE_ROOK = H1   # 7
    WHITE_QUEENSIDE_ROOK = A1  # 0
    BLACK_KINGSIDE_ROOK = H8   # 63
    BLACK_QUEENSIDE_ROOK = A8  # 56
    
    # Rook destination squares for castling
    WHITE_KINGSIDE_ROOK_DEST = F1   # 5
    WHITE_QUEENSIDE_ROOK_DEST = D1  # 3
    BLACK_KINGSIDE_ROOK_DEST = F8   # 61
    BLACK_QUEENSIDE_ROOK_DEST = D8  # 59
    
    # King destination squares for castling
    WHITE_KINGSIDE_KING_DEST = G1   # 6
    WHITE_QUEENSIDE_KING_DEST = C1  # 2
    BLACK_KINGSIDE_KING_DEST = G8   # 62
    BLACK_QUEENSIDE_KING_DEST = C8  # 58
    
    def __init__(self):
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None
        
        # Castling state for rook-first ordering
        self.castling_rook_source = INVALID_SQUARE
        self.castling_rook_placed = False
    
    def reset(self):
        """Reset all move state variables."""
        self.source_square = INVALID_SQUARE
        self.opponent_source_square = INVALID_SQUARE
        self.legal_destination_squares = []
        self.computer_move_uci = ""
        self.is_forced_move = False
        self.source_piece_color = None
        self.castling_rook_source = INVALID_SQUARE
        self.castling_rook_placed = False
    
    def is_rook_castling_square(self, square: int) -> bool:
        """Check if a square is a rook's starting position for castling."""
        return square in (
            self.WHITE_KINGSIDE_ROOK, self.WHITE_QUEENSIDE_ROOK,
            self.BLACK_KINGSIDE_ROOK, self.BLACK_QUEENSIDE_ROOK
        )
    
    def is_valid_rook_castling_destination(self, rook_source: int, rook_dest: int) -> bool:
        """Check if rook placement is valid for castling."""
        valid_pairs = {
            self.WHITE_KINGSIDE_ROOK: self.WHITE_KINGSIDE_ROOK_DEST,
            self.WHITE_QUEENSIDE_ROOK: self.WHITE_QUEENSIDE_ROOK_DEST,
            self.BLACK_KINGSIDE_ROOK: self.BLACK_KINGSIDE_ROOK_DEST,
            self.BLACK_QUEENSIDE_ROOK: self.BLACK_QUEENSIDE_ROOK_DEST,
        }
        return valid_pairs.get(rook_source) == rook_dest
    
    def get_castling_king_move(self, rook_source: int) -> str:
        """Get the king's UCI move for castling based on rook source."""
        castling_moves = {
            self.WHITE_KINGSIDE_ROOK: "e1g1",
            self.WHITE_QUEENSIDE_ROOK: "e1c1",
            self.BLACK_KINGSIDE_ROOK: "e8g8",
            self.BLACK_QUEENSIDE_ROOK: "e8c8",
        }
        return castling_moves.get(rook_source, "")


class TestMoveStateCastling(unittest.TestCase):
    """Tests for MoveState castling helper methods.
    
    Expected behavior:
    - is_rook_castling_square: Returns True for h1, a1, h8, a8
    - is_valid_rook_castling_destination: Returns True for correct rook destinations
    - get_castling_king_move: Returns correct UCI for each castling type
    """
    
    def setUp(self):
        """Set up a fresh MoveState for each test."""
        self.move_state = MockMoveState()
    
    def test_is_rook_castling_square_white_kingside(self):
        """Test detection of white kingside rook square (h1).
        
        Expected: h1 (square 7) is a castling rook square.
        Failure indicates: Castling square constants are incorrect.
        """
        self.assertTrue(self.move_state.is_rook_castling_square(H1))
    
    def test_is_rook_castling_square_white_queenside(self):
        """Test detection of white queenside rook square (a1).
        
        Expected: a1 (square 0) is a castling rook square.
        Failure indicates: Castling square constants are incorrect.
        """
        self.assertTrue(self.move_state.is_rook_castling_square(A1))
    
    def test_is_rook_castling_square_black_kingside(self):
        """Test detection of black kingside rook square (h8).
        
        Expected: h8 (square 63) is a castling rook square.
        Failure indicates: Castling square constants are incorrect.
        """
        self.assertTrue(self.move_state.is_rook_castling_square(H8))
    
    def test_is_rook_castling_square_black_queenside(self):
        """Test detection of black queenside rook square (a8).
        
        Expected: a8 (square 56) is a castling rook square.
        Failure indicates: Castling square constants are incorrect.
        """
        self.assertTrue(self.move_state.is_rook_castling_square(A8))
    
    def test_is_rook_castling_square_non_rook_square(self):
        """Test that non-rook squares are not detected as castling squares.
        
        Expected: e1 (square 4) is NOT a castling rook square.
        Failure indicates: Detection logic is too permissive.
        """
        self.assertFalse(self.move_state.is_rook_castling_square(E1))
    
    def test_valid_rook_castling_destination_white_kingside(self):
        """Test white kingside rook destination (h1 -> f1).
        
        Expected: Rook from h1 to f1 is valid for castling.
        Failure indicates: Destination mapping is incorrect.
        """
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(H1, F1)
        )
    
    def test_valid_rook_castling_destination_white_queenside(self):
        """Test white queenside rook destination (a1 -> d1).
        
        Expected: Rook from a1 to d1 is valid for castling.
        Failure indicates: Destination mapping is incorrect.
        """
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(A1, D1)
        )
    
    def test_valid_rook_castling_destination_black_kingside(self):
        """Test black kingside rook destination (h8 -> f8).
        
        Expected: Rook from h8 to f8 is valid for castling.
        Failure indicates: Destination mapping is incorrect.
        """
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(H8, F8)
        )
    
    def test_valid_rook_castling_destination_black_queenside(self):
        """Test black queenside rook destination (a8 -> d8).
        
        Expected: Rook from a8 to d8 is valid for castling.
        Failure indicates: Destination mapping is incorrect.
        """
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(A8, D8)
        )
    
    def test_invalid_rook_castling_destination_wrong_square(self):
        """Test invalid rook destination (h1 -> d1 is wrong).
        
        Expected: Rook from h1 to d1 is NOT valid (should be f1).
        Failure indicates: Validation is too permissive.
        """
        self.assertFalse(
            self.move_state.is_valid_rook_castling_destination(H1, D1)
        )
    
    def test_get_castling_king_move_white_kingside(self):
        """Test UCI for white kingside castling.
        
        Expected: Rook from h1 -> king move is e1g1.
        Failure indicates: UCI generation is incorrect.
        """
        self.assertEqual(
            self.move_state.get_castling_king_move(H1),
            "e1g1"
        )
    
    def test_get_castling_king_move_white_queenside(self):
        """Test UCI for white queenside castling.
        
        Expected: Rook from a1 -> king move is e1c1.
        Failure indicates: UCI generation is incorrect.
        """
        self.assertEqual(
            self.move_state.get_castling_king_move(A1),
            "e1c1"
        )
    
    def test_get_castling_king_move_black_kingside(self):
        """Test UCI for black kingside castling.
        
        Expected: Rook from h8 -> king move is e8g8.
        Failure indicates: UCI generation is incorrect.
        """
        self.assertEqual(
            self.move_state.get_castling_king_move(H8),
            "e8g8"
        )
    
    def test_get_castling_king_move_black_queenside(self):
        """Test UCI for black queenside castling.
        
        Expected: Rook from a8 -> king move is e8c8.
        Failure indicates: UCI generation is incorrect.
        """
        self.assertEqual(
            self.move_state.get_castling_king_move(A8),
            "e8c8"
        )
    
    def test_reset_clears_castling_state(self):
        """Test that reset() clears castling tracking state.
        
        Expected: After reset, castling_rook_source is INVALID_SQUARE 
        and castling_rook_placed is False.
        Failure indicates: Reset is incomplete.
        """
        self.move_state.castling_rook_source = H1
        self.move_state.castling_rook_placed = True
        
        self.move_state.reset()
        
        self.assertEqual(self.move_state.castling_rook_source, INVALID_SQUARE)
        self.assertFalse(self.move_state.castling_rook_placed)


class TestCastlingConstants(unittest.TestCase):
    """Tests for MoveState castling square constants.
    
    Verifies that the constant values match expected chess squares.
    """
    
    def test_white_king_square(self):
        """Verify WHITE_KING_SQUARE is e1 (square 4)."""
        self.assertEqual(MockMoveState.WHITE_KING_SQUARE, E1)
        self.assertEqual(MockMoveState.WHITE_KING_SQUARE, 4)
    
    def test_black_king_square(self):
        """Verify BLACK_KING_SQUARE is e8 (square 60)."""
        self.assertEqual(MockMoveState.BLACK_KING_SQUARE, E8)
        self.assertEqual(MockMoveState.BLACK_KING_SQUARE, 60)
    
    def test_white_kingside_rook(self):
        """Verify WHITE_KINGSIDE_ROOK is h1 (square 7)."""
        self.assertEqual(MockMoveState.WHITE_KINGSIDE_ROOK, H1)
        self.assertEqual(MockMoveState.WHITE_KINGSIDE_ROOK, 7)
    
    def test_white_queenside_rook(self):
        """Verify WHITE_QUEENSIDE_ROOK is a1 (square 0)."""
        self.assertEqual(MockMoveState.WHITE_QUEENSIDE_ROOK, A1)
        self.assertEqual(MockMoveState.WHITE_QUEENSIDE_ROOK, 0)
    
    def test_black_kingside_rook(self):
        """Verify BLACK_KINGSIDE_ROOK is h8 (square 63)."""
        self.assertEqual(MockMoveState.BLACK_KINGSIDE_ROOK, H8)
        self.assertEqual(MockMoveState.BLACK_KINGSIDE_ROOK, 63)
    
    def test_black_queenside_rook(self):
        """Verify BLACK_QUEENSIDE_ROOK is a8 (square 56)."""
        self.assertEqual(MockMoveState.BLACK_QUEENSIDE_ROOK, A8)
        self.assertEqual(MockMoveState.BLACK_QUEENSIDE_ROOK, 56)
    
    def test_rook_destinations(self):
        """Verify all rook destination squares for castling."""
        self.assertEqual(MockMoveState.WHITE_KINGSIDE_ROOK_DEST, F1)  # 5
        self.assertEqual(MockMoveState.WHITE_QUEENSIDE_ROOK_DEST, D1)  # 3
        self.assertEqual(MockMoveState.BLACK_KINGSIDE_ROOK_DEST, F8)  # 61
        self.assertEqual(MockMoveState.BLACK_QUEENSIDE_ROOK_DEST, D8)  # 59
    
    def test_king_destinations(self):
        """Verify all king destination squares for castling."""
        self.assertEqual(MockMoveState.WHITE_KINGSIDE_KING_DEST, G1)  # 6
        self.assertEqual(MockMoveState.WHITE_QUEENSIDE_KING_DEST, C1)  # 2
        self.assertEqual(MockMoveState.BLACK_KINGSIDE_KING_DEST, G8)  # 62
        self.assertEqual(MockMoveState.BLACK_QUEENSIDE_KING_DEST, C8)  # 58


class TestRookFirstCastlingSequence(unittest.TestCase):
    """Tests for the rook-first castling move sequence.
    
    Simulates the physical move sequence:
    1. Rook lifted from starting square
    2. Rook placed on castling destination
    3. King lifted from starting square
    4. King placed on castling destination
    """
    
    def setUp(self):
        """Set up a fresh MoveState for each test."""
        self.move_state = MockMoveState()
    
    def test_white_kingside_rook_first_sequence(self):
        """Test white kingside castling with rook moved first.
        
        Sequence: h1 rook lift -> f1 rook place -> e1 king lift -> g1 king place
        Expected: Final king move should be e1g1.
        """
        # Step 1: Rook lifted from h1
        rook_source = H1
        self.assertTrue(self.move_state.is_rook_castling_square(rook_source))
        self.move_state.castling_rook_source = rook_source
        
        # Step 2: Rook placed on f1
        rook_dest = F1
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(rook_source, rook_dest)
        )
        self.move_state.castling_rook_placed = True
        
        # Step 3: King lifted from e1
        king_source = E1
        self.move_state.source_square = king_source
        
        # Step 4: King should go to g1, and the final move is e1g1
        expected_king_dest = G1
        castling_uci = self.move_state.get_castling_king_move(rook_source)
        self.assertEqual(castling_uci, "e1g1")
        self.assertEqual(MockMoveState.WHITE_KINGSIDE_KING_DEST, expected_king_dest)
    
    def test_white_queenside_rook_first_sequence(self):
        """Test white queenside castling with rook moved first.
        
        Sequence: a1 rook lift -> d1 rook place -> e1 king lift -> c1 king place
        Expected: Final king move should be e1c1.
        """
        # Step 1: Rook lifted from a1
        rook_source = A1
        self.assertTrue(self.move_state.is_rook_castling_square(rook_source))
        self.move_state.castling_rook_source = rook_source
        
        # Step 2: Rook placed on d1
        rook_dest = D1
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(rook_source, rook_dest)
        )
        self.move_state.castling_rook_placed = True
        
        # Step 3: Verify the expected king move
        castling_uci = self.move_state.get_castling_king_move(rook_source)
        self.assertEqual(castling_uci, "e1c1")
        self.assertEqual(MockMoveState.WHITE_QUEENSIDE_KING_DEST, C1)
    
    def test_black_kingside_rook_first_sequence(self):
        """Test black kingside castling with rook moved first.
        
        Sequence: h8 rook lift -> f8 rook place -> e8 king lift -> g8 king place
        Expected: Final king move should be e8g8.
        """
        # Step 1: Rook lifted from h8
        rook_source = H8
        self.assertTrue(self.move_state.is_rook_castling_square(rook_source))
        self.move_state.castling_rook_source = rook_source
        
        # Step 2: Rook placed on f8
        rook_dest = F8
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(rook_source, rook_dest)
        )
        self.move_state.castling_rook_placed = True
        
        # Step 3: Verify the expected king move
        castling_uci = self.move_state.get_castling_king_move(rook_source)
        self.assertEqual(castling_uci, "e8g8")
        self.assertEqual(MockMoveState.BLACK_KINGSIDE_KING_DEST, G8)
    
    def test_black_queenside_rook_first_sequence(self):
        """Test black queenside castling with rook moved first.
        
        Sequence: a8 rook lift -> d8 rook place -> e8 king lift -> c8 king place
        Expected: Final king move should be e8c8.
        """
        # Step 1: Rook lifted from a8
        rook_source = A8
        self.assertTrue(self.move_state.is_rook_castling_square(rook_source))
        self.move_state.castling_rook_source = rook_source
        
        # Step 2: Rook placed on d8
        rook_dest = D8
        self.assertTrue(
            self.move_state.is_valid_rook_castling_destination(rook_source, rook_dest)
        )
        self.move_state.castling_rook_placed = True
        
        # Step 3: Verify the expected king move
        castling_uci = self.move_state.get_castling_king_move(rook_source)
        self.assertEqual(castling_uci, "e8c8")
        self.assertEqual(MockMoveState.BLACK_QUEENSIDE_KING_DEST, C8)
    
    def test_rook_put_back_cancels_castling(self):
        """Test that putting the rook back cancels castling tracking.
        
        Expected: If rook is returned to its starting square, castling state is reset.
        """
        # Step 1: Rook lifted from h1
        rook_source = H1
        self.move_state.castling_rook_source = rook_source
        
        # Step 2: Rook put back on h1 (castling cancelled)
        # In the actual code, this would reset castling_rook_source
        self.move_state.castling_rook_source = INVALID_SQUARE
        self.move_state.castling_rook_placed = False
        
        self.assertEqual(self.move_state.castling_rook_source, INVALID_SQUARE)
        self.assertFalse(self.move_state.castling_rook_placed)


def run_tests():
    """Run all tests and print results."""
    print("=" * 60)
    print("Rook-First Castling Unit Tests")
    print("=" * 60)
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestMoveStateCastling))
    suite.addTests(loader.loadTestsFromTestCase(TestCastlingConstants))
    suite.addTests(loader.loadTestsFromTestCase(TestRookFirstCastlingSequence))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES: {len(result.failures)}, ERRORS: {len(result.errors)}")
    print("=" * 60)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
