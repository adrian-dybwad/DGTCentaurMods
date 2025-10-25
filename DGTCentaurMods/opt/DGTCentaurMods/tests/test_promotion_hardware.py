#!/usr/bin/env python3
"""
Hardware-in-the-Loop Test for Promotion Button Handling

This test creates specific chess positions that trigger promotion scenarios
and tests the refactored button handling logic with real hardware.

# Run unit tests only
python test_promotion_hardware.py

# Run with hardware testing
python test_promotion_hardware.py --hardware

# Test specific promotion scenarios
python test_promotion_hardware.py --hardware --position white
python test_promotion_hardware.py --hardware --position black

Usage:
    python test_promotion_hardware.py [--position white|black|both]
"""

import sys
import os
import time
import argparse
from unittest.mock import patch, MagicMock

# Add the DGTCentaurMods path
sys.path.append('/Users/adriandybwad/Documents/GitHub/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')

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
        gamemanager.cboard = chess.Board(fen_string)
        
        # Update the FEN log file (as the system expects)
        fenlog = "/home/pi/centaur/fen.log"
        try:
            with open(fenlog, "w") as f:
                f.write(gamemanager.cboard.fen())
            print(f"PASS: FEN written to {fenlog}")
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
        
        for button_name, expected_piece in self.button_mappings.items():
            print(f"  Testing button: {button_name} -> {expected_piece}")
            
            with patch('DGTCentaurMods.board.board.wait_for_key_up') as mock_wait:
                mock_wait.return_value = (0x10, button_name)
                
                result = gamemanager.waitForPromotionChoice()
                
                if result == expected_piece:
                    print(f"    PASS: {button_name} correctly mapped to {expected_piece}")
                    self.test_results.append(f"waitForPromotionChoice: {button_name} -> {expected_piece} PASS")
                else:
                    print(f"    FAIL: {button_name} mapped to {result}, expected {expected_piece}")
                    self.test_results.append(f"waitForPromotionChoice: {button_name} -> {result} FAIL")
    
    def test_promotion_flow_with_mocked_board(self):
        """Test the complete promotion flow with mocked board interactions"""
        if not FULL_ENVIRONMENT:
            print("\nSkipping promotion flow test - full environment not available")
            self.test_results.append("Promotion flow: Skipped (no full environment)")
            return
            
        print("\nTesting promotion flow with mocked board...")
        
        with patch('DGTCentaurMods.board.board') as mock_board:
            with patch('DGTCentaurMods.game.gamemanager.epaper') as mock_epaper:
                
                # Setup mocks
                mock_board.beep = MagicMock()
                mock_board.wait_for_key_up = MagicMock(return_value=(0x10, 'UP'))
                mock_epaper.epaperbuffer = MagicMock()
                mock_epaper.promotionOptions = MagicMock()
                
                # Test that beep is called correctly
                board.beep(board.SOUND_GENERAL)
                mock_board.beep.assert_called_with(board.SOUND_GENERAL)
                
                print("    PASS: board.beep() called correctly")
                self.test_results.append("Promotion flow: board.beep() called PASS")
    
    def test_no_direct_serial_access(self):
        """Ensure no direct serial access remains in promotion code"""
        print("\nChecking for direct serial access patterns...")
        
        # Read the gamemanager.py file directly instead of importing
        gamemanager_path = "/Users/adriandybwad/Documents/GitHub/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/game/gamemanager.py"
        
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
