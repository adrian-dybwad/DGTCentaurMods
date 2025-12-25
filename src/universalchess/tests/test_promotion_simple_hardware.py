#!/usr/bin/env python3
"""
Simple Hardware Tests for Promotion Button Handling

This test module provides simpler automated tests and optional
hardware integration tests for promotion functionality.

USAGE:
    # Run automated tests only (no hardware required)
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    python3 -m pytest DGTCentaurMods/tests/test_promotion_simple_hardware.py -v
    
    # Run with hardware tests (requires manual interaction)
    python3 DGTCentaurMods/tests/test_promotion_simple_hardware.py --hardware --position white
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


class TestFunctionExistence(unittest.TestCase):
    """
    Tests for required function existence.
    
    Verifies that all required promotion-related functions exist
    in the appropriate modules.
    """
    
    @unittest.skipUnless(FULL_ENVIRONMENT, "Full DGTCentaurMods environment not available")
    def test_wait_for_promotion_choice_exists(self):
        """
        Test that waitForPromotionChoice function exists.
        
        Expected: Function exists in gamemanager module.
        Failure indicates: Function was not implemented.
        """
        self.assertTrue(
            hasattr(gamemanager, 'waitForPromotionChoice'),
            "waitForPromotionChoice function not found in gamemanager"
        )
    
    @unittest.skipUnless(FULL_ENVIRONMENT, "Full DGTCentaurMods environment not available")
    def test_board_beep_exists(self):
        """
        Test that board.beep function exists.
        
        Expected: Function exists in board module.
        Failure indicates: Board module is missing beep function.
        """
        self.assertTrue(
            hasattr(board, 'beep'),
            "board.beep function not found"
        )
    
    @unittest.skipUnless(FULL_ENVIRONMENT, "Full DGTCentaurMods environment not available")
    def test_board_wait_for_key_up_exists(self):
        """
        Test that board.wait_for_key_up function exists.
        
        Expected: Function exists in board module.
        Failure indicates: Board module is missing wait_for_key_up function.
        """
        self.assertTrue(
            hasattr(board, 'wait_for_key_up'),
            "board.wait_for_key_up function not found"
        )


class TestNoSerialAccess(unittest.TestCase):
    """
    Tests to verify no direct serial access remains.
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
    
    def test_no_direct_serial_access_patterns(self):
        """
        Test that gamemanager.py has no direct serial access.
        
        Expected: No forbidden patterns in source code.
        Failure indicates: Refactoring incomplete - direct serial access
        should be replaced with board API calls.
        """
        try:
            with open(self.GAMEMANAGER_PATH, 'r') as f:
                content = f.read()
        except FileNotFoundError:
            self.skipTest(f"Could not read {self.GAMEMANAGER_PATH}")
        
        violations = [p for p in self.FORBIDDEN_PATTERNS if p in content]
        self.assertEqual(
            violations, [],
            f"Found forbidden direct serial access patterns: {violations}"
        )


def run_hardware_promotion_test(color="white"):
    """
    Run interactive hardware test for promotion.
    
    This test requires manual interaction with the board.
    Uses logger instead of print for proper logging hygiene.
    
    Args:
        color: "white" or "black" for which promotion to test.
    """
    if not FULL_ENVIRONMENT:
        logger.error("Full DGTCentaurMods environment not available")
        return
    
    logger.info(f"Testing {color} promotion with hardware...")
    logger.info("This test requires manual interaction with the board")
    
    # Create promotion position
    if color.lower() == "white":
        fen = "rnbqkbnr/pppppppp/8/8/8/7P/PPPPPPP1/RNBQKBNR w KQkq - 0 1"
    else:
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBNR b KQkq - 0 1"
    
    logger.info(f"Position: {fen}")
    
    # Load the position
    try:
        gamemanager.setBoard(chess.Board(fen))
        from universalchess.managers.game import write_fen_log
        write_fen_log(gamemanager.getFEN())
        logger.info("Position loaded successfully")
    except Exception as e:
        logger.error(f"Could not load position: {e}")
        return
    
    logger.info("\nManual Test Instructions:")
    logger.info("1. Set up the board with the loaded position")
    logger.info("2. Make a move that triggers pawn promotion")
    logger.info("3. When promotion dialog appears, test each button:")
    logger.info("   - BACK button -> Knight")
    logger.info("   - TICK button -> Bishop")
    logger.info("   - UP button -> Queen")
    logger.info("   - DOWN button -> Rook")
    logger.info("4. Verify the promotion works correctly")
    
    input("\nPress Enter when ready to start...")
    
    promotion_results = []
    
    def event_callback(event):
        logger.info(f"Event: {event}")
    
    def move_callback(move):
        logger.info(f"Move: {move}")
        if len(move) > 4:  # Promotion move
            promoted_piece = move[-1]
            logger.info(f"PROMOTION DETECTED: {promoted_piece}")
            promotion_results.append(promoted_piece)
    
    def key_callback(key):
        logger.info(f"Key: {key}")
    
    # Start the game manager
    logger.info("Starting game manager...")
    gamemanager.subscribeGame(event_callback, move_callback, key_callback)
    
    logger.info("Game manager started. Make your promotion move now...")
    logger.info("Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nTest stopped")
        gamemanager.unsubscribeGame()
    
    if promotion_results:
        logger.info(f"Promotions detected: {promotion_results}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Simple promotion button test")
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="Run hardware tests"
    )
    parser.add_argument(
        "--position",
        choices=["white", "black", "both"],
        default="both",
        help="Which positions to test"
    )
    
    args = parser.parse_args()
    
    if args.hardware:
        if args.position in ["white", "both"]:
            run_hardware_promotion_test("white")
        if args.position in ["black", "both"]:
            run_hardware_promotion_test("black")
    else:
        # Run automated unit tests
        unittest.main(argv=[''], verbosity=2, exit=True)


if __name__ == "__main__":
    main()
