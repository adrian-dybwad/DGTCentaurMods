#!/usr/bin/env python3
"""
Simple Hardware Test for Promotion Button Handling

This test works with the actual hardware without mocking.
"""

import sys
import os
import time
import argparse

# Add the DGTCentaurMods path
sys.path.append('/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods')

try:
    import chess
    from DGTCentaurMods.game import gamemanager
    from DGTCentaurMods.board import board
    FULL_ENVIRONMENT = True
    print("Full DGTCentaurMods environment loaded successfully")
except ImportError as e:
    print(f"Warning: Could not import DGTCentaurMods modules: {e}")
    print("Running in limited test mode...")
    FULL_ENVIRONMENT = False

class SimplePromotionTester:
    """Simple tester for promotion functionality"""
    
    def __init__(self):
        self.test_results = []
    
    def test_function_exists(self):
        """Test that required functions exist"""
        print("\nTesting function existence...")
        
        if not FULL_ENVIRONMENT:
            print("  Skipped - no full environment")
            return
            
        # Test waitForPromotionChoice exists
        if hasattr(gamemanager, 'waitForPromotionChoice'):
            print("  PASS: waitForPromotionChoice function exists")
            self.test_results.append("waitForPromotionChoice: exists PASS")
        else:
            print("  FAIL: waitForPromotionChoice function missing")
            self.test_results.append("waitForPromotionChoice: missing FAIL")
        
        # Test board functions exist
        if hasattr(board, 'beep'):
            print("  PASS: board.beep function exists")
            self.test_results.append("board.beep: exists PASS")
        else:
            print("  FAIL: board.beep function missing")
            self.test_results.append("board.beep: missing FAIL")
            
        if hasattr(board, 'wait_for_key_up'):
            print("  PASS: board.wait_for_key_up function exists")
            self.test_results.append("board.wait_for_key_up: exists PASS")
        else:
            print("  FAIL: board.wait_for_key_up function missing")
            self.test_results.append("board.wait_for_key_up: missing FAIL")
    
    def test_no_serial_access(self):
        """Test that no direct serial access remains"""
        print("\nTesting for direct serial access patterns...")
        
        gamemanager_path = "/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/game/gamemanager.py"
        
        try:
            with open(gamemanager_path, 'r') as f:
                content = f.read()
            
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
                if pattern in content:
                    violations.append(pattern)
            
            if not violations:
                print("  PASS: No direct serial access patterns found!")
                self.test_results.append("Serial access: No violations PASS")
            else:
                print(f"  FAIL: Found forbidden patterns: {violations}")
                self.test_results.append(f"Serial access: Violations found FAIL")
                
        except FileNotFoundError:
            print(f"  WARNING: Could not read {gamemanager_path}")
            self.test_results.append("Serial access: Could not read file")
    
    def test_hardware_promotion(self, color="white"):
        """Test promotion with actual hardware"""
        if not FULL_ENVIRONMENT:
            print(f"\nSkipping {color} hardware test - no full environment")
            return
            
        print(f"\nTesting {color} promotion with hardware...")
        print("This test requires manual interaction with the DGT Centaur board")
        
        # Create a simple promotion position
        if color.lower() == "white":
            fen = "rnbqkbnr/pppppppp/8/8/8/7P/PPPPPPP1/RNBQKBNR w KQkq - 0 1"
        else:
            fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP1/RNBQKBNR b KQkq - 0 1"
        
        print(f"Position: {fen}")
        
        # Load the position
        try:
            gamemanager.cboard = chess.Board(fen)
            fenlog = "/home/pi/centaur/fen.log"
            with open(fenlog, "w") as f:
                f.write(gamemanager.cboard.fen())
            print(f"Position loaded to {fenlog}")
        except Exception as e:
            print(f"Could not load position: {e}")
            return
        
        print("\nManual Test Instructions:")
        print("1. Set up the board with the loaded position")
        print("2. Make a move that triggers pawn promotion")
        print("3. When promotion dialog appears, test each button:")
        print("   - BACK button -> Knight")
        print("   - TICK button -> Bishop") 
        print("   - UP button -> Queen")
        print("   - DOWN button -> Rook")
        print("4. Verify the promotion works correctly")
        
        input("\nPress Enter when ready to start...")
        
        # Set up callbacks
        def event_callback(event):
            print(f"Event: {event}")
        
        def move_callback(move):
            print(f"Move: {move}")
            if len(move) > 4:  # Promotion move
                promoted_piece = move[-1]
                print(f"PROMOTION DETECTED: {promoted_piece}")
                self.test_results.append(f"Hardware test ({color}): Promotion to {promoted_piece} PASS")
        
        def key_callback(key):
            print(f"Key: {key}")
        
        # Start the game manager
        print("Starting game manager...")
        gamemanager.subscribeGame(event_callback, move_callback, key_callback)
        
        print("Game manager started. Make your promotion move now...")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nTest stopped")
            gamemanager.unsubscribeGame()
    
    def run_tests(self, hardware_test=False, position="both"):
        """Run all tests"""
        print("Starting Simple Promotion Tests")
        print("=" * 40)
        
        # Always run these tests
        self.test_function_exists()
        self.test_no_serial_access()
        
        # Hardware tests (optional)
        if hardware_test and FULL_ENVIRONMENT:
            if position in ["white", "both"]:
                self.test_hardware_promotion("white")
            if position in ["black", "both"]:
                self.test_hardware_promotion("black")
        
        # Print results
        print("\nTest Results:")
        print("=" * 20)
        for result in self.test_results:
            print(f"  {result}")
        
        passed = sum(1 for r in self.test_results if "PASS" in r)
        total = len(self.test_results)
        print(f"\nResults: {passed}/{total} tests passed")

def main():
    parser = argparse.ArgumentParser(description="Simple promotion button test")
    parser.add_argument("--hardware", action="store_true", 
                       help="Run hardware tests")
    parser.add_argument("--position", choices=["white", "black", "both"], default="both",
                       help="Which positions to test")
    
    args = parser.parse_args()
    
    tester = SimplePromotionTester()
    tester.run_tests(hardware_test=args.hardware, position=args.position)

if __name__ == "__main__":
    main()
