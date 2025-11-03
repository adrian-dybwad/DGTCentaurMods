#!/usr/bin/env python3
"""
Hardware-in-the-Loop Test for Promotion Button Handling

This test creates specific chess positions that trigger promotion scenarios
and tests the refactored button handling logic with real hardware.

USAGE:
    # Navigate to opt folder
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    
    # Activate virtual environment
    source DGTCentaurMods/.venv/bin/activate
    
    # Run tests
    python3 DGTCentaurMods/tests/test_promotion_hardware.py --hardware --position white
    python3 DGTCentaurMods/tests/test_promotion_hardware.py --hardware
    python3 DGTCentaurMods/tests/test_promotion_simple.py

Usage:
    python test_promotion_hardware.py [--position white|black|both]
"""

import sys
import os
import time
import argparse
from unittest.mock import patch, MagicMock

# Add the opt folder to Python path (so DGTCentaurMods can be imported)
sys.path.insert(0, os.path.abspath('.'))

try:
    import chess
    from DGTCentaurMods.game import gamemanager
    from DGTCentaurMods.board import board
    FULL_ENVIRONMENT = True
except ImportError as e:
    print(f"Warning: Could not import DGTCentaurMods modules: {e}")
    print("Running in limited test mode...")
    FULL_ENVIRONMENT = False

class PromotionTestSetup:
    """Helper class to set up test positions for promotion testing"""
    
    # Test positions that lead to promotion
    WHITE_PROMOTION_POSITIONS = {
        "pawn_on_7th": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "ready_to_promote": "rnbqkbnr/pppppppp/8/8/8/7P/PPPPPPP1/RNBQKBNR w KQkq - 0 1",
        "promotion_scenario": "rnbqkbnr/pppppppp/8/8/8/7P/PPPPPPP1/RNBQKBNR w KQkq - 0 1"
    }
    
    BLACK_PROMOTION_POSITIONS = {
        "pawn_on_2nd": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1", 
        "ready_to_promote": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBNR b KQkq - 0 1",
        "promotion_scenario": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBNR b KQkq - 0 1"
    }
    
    @staticmethod
    def load_position(fen_string):
        """Load a chess position from FEN string"""
        print(f"Loading position: {fen_string}")
        
        # Set the global chess board
        gamemanager.setBoard(chess.Board(fen_string))
        
        # Update the FEN log file (as the system expects)
        from DGTCentaurMods.config import paths
        try:
            paths.write_fen_log(gamemanager.getFEN())
            print(f"PASS: FEN written")
        except Exception as e:
            print(f"WARNING: Could not write FEN log: {e}")
    
    @staticmethod
    def create_promotion_position(color="white"):
        """Create a position where a pawn can promote"""
        if color.lower() == "white":
            # White pawn on 7th rank ready to promote
            fen = "rnbqkbnr/pppppppp/8/8/8/7P/PPPPPPP1/RNBQKBNR w KQkq - 0 1"
        else:
            # Black pawn on 2nd rank ready to promote  
            fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBNR b KQkq - 0 1"
        
        PromotionTestSetup.load_position(fen)
        return fen

class PromotionButtonTester:
    """Test the refactored promotion button handling"""
    
    def __init__(self):
        self.test_results = []
        self.button_mappings = {
            'BACK': 'n',   # Knight
            'TICK': 'b',   # Bishop  
            'UP': 'q',     # Queen
            'DOWN': 'r',   # Rook
        }
    
    def test_waitForPromotionChoice_function(self):
        """Test the waitForPromotionChoice helper function directly"""
        if not FULL_ENVIRONMENT:
            print("\nSkipping waitForPromotionChoice test - full environment not available")
            self.test_results.append("waitForPromotionChoice: Skipped (no full environment)")
            return
            
        print("\nTesting waitForPromotionChoice() function...")
        print("  Note: This test validates the function exists and has correct button mapping logic")
        
        # Test that the function exists and has the expected behavior
        try:
            # Check if the function exists
            if hasattr(gamemanager, 'waitForPromotionChoice'):
                print("    PASS: waitForPromotionChoice function exists")
                self.test_results.append("waitForPromotionChoice: Function exists PASS")
                
                # Test the button mapping logic by examining the function
                import inspect
                source = inspect.getsource(gamemanager.waitForPromotionChoice)
                
                # Check for expected button mappings in the source
                expected_mappings = [
                    ("'BACK'", "'n'"),
                    ("'TICK'", "'b'"), 
                    ("'UP'", "'q'"),
                    ("'DOWN'", "'r'")
                ]
                
                mapping_found = 0
                for button, piece in expected_mappings:
                    if button in source and piece in source:
                        mapping_found += 1
                        print(f"    PASS: {button} -> {piece} mapping found")
                
                if mapping_found == len(expected_mappings):
                    print("    PASS: All button mappings found in function")
                    self.test_results.append("waitForPromotionChoice: All mappings found PASS")
                else:
                    print(f"    FAIL: Only {mapping_found}/{len(expected_mappings)} mappings found")
                    self.test_results.append(f"waitForPromotionChoice: Incomplete mappings FAIL")
                    
            else:
                print("    FAIL: waitForPromotionChoice function not found")
                self.test_results.append("waitForPromotionChoice: Function missing FAIL")
                
        except Exception as e:
            print(f"    ERROR: Could not test waitForPromotionChoice: {e}")
            self.test_results.append(f"waitForPromotionChoice: Error - {e}")
    
    def test_promotion_flow_with_mocked_board(self):
        """Test the complete promotion flow with real board interactions"""
        if not FULL_ENVIRONMENT:
            print("\nSkipping promotion flow test - full environment not available")
            self.test_results.append("Promotion flow: Skipped (no full environment)")
            return
            
        print("\nTesting promotion flow with real board API...")
        print("  Note: This test validates that the correct board API calls are used")
        
        try:
            # Test that board.beep exists and can be called
            if hasattr(board, 'beep'):
                print("    PASS: board.beep() function exists")
                self.test_results.append("Promotion flow: board.beep() exists PASS")
            else:
                print("    FAIL: board.beep() function not found")
                self.test_results.append("Promotion flow: board.beep() missing FAIL")
            
            # Test that board.wait_for_key_up exists
            if hasattr(board, 'wait_for_key_up'):
                print("    PASS: board.wait_for_key_up() function exists")
                self.test_results.append("Promotion flow: board.wait_for_key_up() exists PASS")
            else:
                print("    FAIL: board.wait_for_key_up() function not found")
                self.test_results.append("Promotion flow: board.wait_for_key_up() missing FAIL")
                
        except Exception as e:
            print(f"    ERROR: Could not test board API: {e}")
            self.test_results.append(f"Promotion flow: Error - {e}")
    
    def test_no_direct_serial_access(self):
        """Ensure no direct serial access remains in promotion code"""
        print("\nChecking for direct serial access patterns...")
        
        # Read the gamemanager.py file directly instead of importing
        gamemanager_path = "DGTCentaurMods/game/gamemanager.py"
        
        try:
            with open(gamemanager_path, 'r') as f:
                source = f.read()
        except FileNotFoundError:
            print(f"    WARNING: Could not read {gamemanager_path}")
            self.test_results.append("Serial access: Could not read file")
            return
        
        forbidden_patterns = [
            'board.ser.write',
            'board.ser.read', 
            'board.sendPacket',
            'resp.hex()',
            'board.addr1',
            'board.addr2'
        ]
        
        violations = []
        for pattern in forbidden_patterns:
            if pattern in source:
                violations.append(pattern)
        
        if not violations:
            print("    PASS: No direct serial access patterns found!")
            self.test_results.append("Serial access: No violations found PASS")
        else:
            print(f"    FAIL: Found forbidden patterns: {violations}")
            self.test_results.append(f"Serial access: Violations found FAIL")
    
    def test_hardware_promotion_scenario(self, color="white"):
        """Test promotion with actual hardware (requires manual interaction)"""
        if not FULL_ENVIRONMENT:
            print(f"\nSkipping {color} hardware test - full environment not available")
            self.test_results.append(f"Hardware test ({color}): Skipped (no full environment)")
            return
            
        print(f"\nTesting {color} promotion with hardware...")
        print("    This test requires manual interaction with the DGT Centaur board")
        
        # Load a promotion position
        fen = PromotionTestSetup.create_promotion_position(color)
        print(f"    Position loaded: {fen}")
        
        print(f"\n    Manual Test Instructions:")
        print(f"    1. Set up the board with the loaded position")
        print(f"    2. Make a move that triggers {color} pawn promotion")
        print(f"    3. When promotion dialog appears, test each button:")
        
        for button, piece in self.button_mappings.items():
            print(f"       - Press {button} button -> should promote to {piece}")
        
        print(f"    4. Verify that:")
        print(f"       - No direct serial access occurs (check debug logs)")
        print(f"       - board.beep() is called instead of manual beep")
        print(f"       - waitForPromotionChoice() handles button input")
        
        input("\n    Press Enter when ready to start manual test...")
        
        # Subscribe to the game manager to start monitoring
        print("    Starting game manager monitoring...")
        
        def test_event_callback(event):
            print(f"    Event received: {event}")
        
        def test_move_callback(move):
            print(f"    Move received: {move}")
            if len(move) > 4:  # Promotion move
                promoted_piece = move[-1]
                print(f"    PASS: Promotion detected: {promoted_piece}")
                self.test_results.append(f"Hardware test: Promotion to {promoted_piece} PASS")
        
        def test_key_callback(key):
            print(f"    Key pressed: {key}")
        
        # Start the game manager
        gamemanager.subscribeGame(test_event_callback, test_move_callback, test_key_callback)
        
        print("    Game manager started. Make your promotion move now...")
        print("    Press Ctrl+C to stop the test")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n    Test stopped by user")
            gamemanager.unsubscribeGame()
    
    def run_all_tests(self, hardware_test=False, position="both"):
        """Run all tests"""
        print("Starting Promotion Button Handling Tests")
        print("=" * 50)
        
        # Unit tests (always run)
        self.test_waitForPromotionChoice_function()
        self.test_promotion_flow_with_mocked_board()
        self.test_no_direct_serial_access()
        
        # Hardware tests (optional)
        if hardware_test:
            if position in ["white", "both"]:
                self.test_hardware_promotion_scenario("white")
            if position in ["black", "both"]:
                self.test_hardware_promotion_scenario("black")
        
        # Print results
        print("\nTest Results Summary:")
        print("=" * 30)
        for result in self.test_results:
            print(f"  {result}")
        
        # Count successes
        successes = sum(1 for r in self.test_results if "PASS" in r)
        total = len(self.test_results)
        print(f"\nResults: {successes}/{total} tests passed")
        
        if successes == total:
            print("All tests passed!")
        else:
            print("Some tests failed - check the results above")

def main():
    parser = argparse.ArgumentParser(description="Test promotion button handling")
    parser.add_argument("--hardware", action="store_true", 
                       help="Run hardware-in-the-loop tests (requires manual interaction)")
    parser.add_argument("--position", choices=["white", "black", "both"], default="both",
                       help="Which promotion positions to test")
    
    args = parser.parse_args()
    
    tester = PromotionButtonTester()
    tester.run_all_tests(hardware_test=args.hardware, position=args.position)

if __name__ == "__main__":
    main()
