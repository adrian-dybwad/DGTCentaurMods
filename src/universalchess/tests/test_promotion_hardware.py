#!/usr/bin/env python3
"""
Hardware-in-the-Loop Tests for Promotion Button Handling

This test module contains both automated unit tests and optional
hardware integration tests that require manual interaction.

The automated tests verify:
- waitForPromotionChoice function exists with correct button mappings
- Board API functions exist (board.beep, board.wait_for_key_up)
- No direct serial access patterns in gamemanager.py

USAGE:
    # Run automated tests only (no hardware required)
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    python3 -m pytest DGTCentaurMods/tests/test_promotion_hardware.py -v
    
    # Run with hardware tests (requires manual interaction)
    python3 DGTCentaurMods/tests/test_promotion_hardware.py --hardware --position white
"""

import sys
import os
import time
import argparse
import unittest
import logging

# Set up logging for hardware tests
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add the opt folder to Python path (so DGTCentaurMods can be imported)
sys.path.insert(0, os.path.abspath('.'))

try:
    import chess
    from universalchess.game import gamemanager
    from universalchess.board import board
    FULL_ENVIRONMENT = True
except ImportError:
    FULL_ENVIRONMENT = False


class PromotionTestSetup:
    """Helper class to set up test positions for promotion testing."""
    
    WHITE_PROMOTION_FEN = "rnbqkbnr/pppppppp/8/8/8/7P/PPPPPPP1/RNBQKBNR w KQkq - 0 1"
    BLACK_PROMOTION_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBNR b KQkq - 0 1"
    
    @classmethod
    def load_position(cls, fen_string):
        """
        Load a chess position from FEN string.
        
        Args:
            fen_string: FEN notation string for the position.
            
        Returns:
            True if position loaded successfully, False otherwise.
        """
        if not FULL_ENVIRONMENT:
            return False
        
        gamemanager.setBoard(chess.Board(fen_string))
        
        try:
            from universalchess.managers.game import write_fen_log
            write_fen_log(gamemanager.getFEN())
            return True
        except Exception:
            return False
    
    @classmethod
    def create_promotion_position(cls, color="white"):
        """
        Create a position where a pawn can promote.
        
        Args:
            color: "white" or "black" for which side can promote.
            
        Returns:
            The FEN string for the position.
        """
        fen = cls.WHITE_PROMOTION_FEN if color.lower() == "white" else cls.BLACK_PROMOTION_FEN
        cls.load_position(fen)
        return fen


class TestWaitForPromotionChoiceFunction(unittest.TestCase):
    """
    Tests for the waitForPromotionChoice function.
    
    Verifies that the function exists and has correct button mapping
    logic by inspecting the source code.
    """
    
    EXPECTED_BUTTON_MAPPINGS = [
        ("'BACK'", "'n'"),
        ("'TICK'", "'b'"),
        ("'UP'", "'q'"),
        ("'DOWN'", "'r'")
    ]
    
    @unittest.skipUnless(FULL_ENVIRONMENT, "Full DGTCentaurMods environment not available")
    def test_wait_for_promotion_choice_exists(self):
        """
        Test that waitForPromotionChoice function exists.
        
        Expected: Function exists in gamemanager module.
        Failure indicates: Function was not implemented or incorrectly named.
        """
        self.assertTrue(
            hasattr(gamemanager, 'waitForPromotionChoice'),
            "waitForPromotionChoice function not found in gamemanager"
        )
    
    @unittest.skipUnless(FULL_ENVIRONMENT, "Full DGTCentaurMods environment not available")
    def test_wait_for_promotion_choice_has_correct_mappings(self):
        """
        Test that waitForPromotionChoice has all button mappings.
        
        Expected: All button -> piece mappings found in function source.
        Failure indicates: Button mapping logic is incomplete.
        """
        import inspect
        source = inspect.getsource(gamemanager.waitForPromotionChoice)
        
        for button, piece in self.EXPECTED_BUTTON_MAPPINGS:
            with self.subTest(button=button, piece=piece):
                self.assertIn(button, source, f"Button {button} not found in function")
                self.assertIn(piece, source, f"Piece {piece} not found in function")


class TestBoardApiFunctions(unittest.TestCase):
    """
    Tests for board API function existence.
    
    Verifies that the abstracted board functions are available.
    """
    
    @unittest.skipUnless(FULL_ENVIRONMENT, "Full DGTCentaurMods environment not available")
    def test_board_beep_exists(self):
        """
        Test that board.beep() function exists.
        
        Expected: Function exists in board module.
        Failure indicates: Board module is missing beep function.
        """
        self.assertTrue(
            hasattr(board, 'beep'),
            "board.beep() function not found"
        )
    
    @unittest.skipUnless(FULL_ENVIRONMENT, "Full DGTCentaurMods environment not available")
    def test_board_wait_for_key_up_exists(self):
        """
        Test that board.wait_for_key_up() function exists.
        
        Expected: Function exists in board module.
        Failure indicates: Board module is missing wait_for_key_up function.
        """
        self.assertTrue(
            hasattr(board, 'wait_for_key_up'),
            "board.wait_for_key_up() function not found"
        )


class TestNoDirectSerialAccess(unittest.TestCase):
    """
    Tests to ensure direct serial access has been removed.
    """
    
    GAMEMANAGER_PATH = "DGTCentaurMods/game/gamemanager.py"
    
    FORBIDDEN_PATTERNS = [
        'board.ser.write',
        'board.ser.read',
        'board.sendPacket',
        'resp.hex()',
        'board.addr1',
        'board.addr2'
    ]
    
    def test_no_direct_serial_access_in_gamemanager(self):
        """
        Test that gamemanager.py has no direct serial access patterns.
        
        Expected: No forbidden patterns in source code.
        Failure indicates: Refactoring incomplete - serial access remains.
        """
        try:
            with open(self.GAMEMANAGER_PATH, 'r') as f:
                source = f.read()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        violations = [p for p in self.FORBIDDEN_PATTERNS if p in source]
        self.assertEqual(
            violations, [],
            f"Found forbidden direct serial access patterns: {violations}"
        )


def run_hardware_test(color="white"):
    """
    Run interactive hardware test for promotion.
    
    This test requires manual interaction with the board
    and is not suitable for automated testing.
    
    Args:
        color: "white" or "black" for which promotion to test.
    """
    if not FULL_ENVIRONMENT:
        logger.error("Full DGTCentaurMods environment not available")
        return
    
    button_mappings = {
        'BACK': 'Knight (n)',
        'TICK': 'Bishop (b)',
        'UP': 'Queen (q)',
        'DOWN': 'Rook (r)',
    }
    
    logger.info(f"Starting {color} promotion hardware test...")
    
    fen = PromotionTestSetup.create_promotion_position(color)
    logger.info(f"Position loaded: {fen}")
    
    logger.info("\nManual Test Instructions:")
    logger.info("1. Set up the board with the loaded position")
    logger.info(f"2. Make a move that triggers {color} pawn promotion")
    logger.info("3. When promotion dialog appears, test each button:")
    for button, piece in button_mappings.items():
        logger.info(f"   - {button} button -> {piece}")
    logger.info("4. Verify that:")
    logger.info("   - No direct serial access occurs (check debug logs)")
    logger.info("   - board.beep() is called instead of manual beep")
    logger.info("   - waitForPromotionChoice() handles button input")
    
    input("\nPress Enter when ready to start manual test...")
    
    promotion_detected = []
    
    def event_callback(event):
        logger.info(f"Event received: {event}")
    
    def move_callback(move):
        logger.info(f"Move received: {move}")
        if len(move) > 4:  # Promotion move has 5 characters
            promoted_piece = move[-1]
            logger.info(f"PROMOTION DETECTED: promoted to {promoted_piece}")
            promotion_detected.append(promoted_piece)
    
    def key_callback(key):
        logger.info(f"Key pressed: {key}")
    
    gamemanager.subscribeGame(event_callback, move_callback, key_callback)
    
    logger.info("Game manager started. Make your promotion move now...")
    logger.info("Press Ctrl+C to stop the test")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nTest stopped by user")
        gamemanager.unsubscribeGame()
    
    if promotion_detected:
        logger.info(f"TEST PASSED: Detected promotions: {promotion_detected}")
    else:
        logger.info("No promotions detected during test")


def main():
    """Main entry point for running tests."""
    parser = argparse.ArgumentParser(description="Promotion button handling tests")
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="Run interactive hardware tests (requires manual interaction)"
    )
    parser.add_argument(
        "--position",
        choices=["white", "black", "both"],
        default="both",
        help="Which promotion positions to test (hardware mode only)"
    )
    
    args = parser.parse_args()
    
    if args.hardware:
        # Run hardware tests
        if args.position in ["white", "both"]:
            run_hardware_test("white")
        if args.position in ["black", "both"]:
            run_hardware_test("black")
    else:
        # Run automated unit tests
        unittest.main(argv=[''], verbosity=2, exit=True)


if __name__ == "__main__":
    main()
