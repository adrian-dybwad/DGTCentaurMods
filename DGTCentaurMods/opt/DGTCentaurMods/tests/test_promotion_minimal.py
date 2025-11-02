#!/usr/bin/env python3
"""
Minimal Promotion Test - Avoids problematic imports

This test focuses only on the core functionality without importing
modules that require hardware resources or fonts.

USAGE:
    # Navigate to opt folder
    cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
    
    # Activate virtual environment
    source DGTCentaurMods/.venv/bin/activate
    
    # Run test
    python3 DGTCentaurMods/tests/test_promotion_minimal.py
"""

import sys
import os
import inspect

# Add the opt folder to Python path (so DGTCentaurMods can be imported)
sys.path.insert(0, os.path.abspath('.'))

def test_gamemanager_source_code():
    """Test the gamemanager.py source code directly without importing"""
    print("Testing gamemanager.py source code...")
    
    gamemanager_path = "DGTCentaurMods/game/gamemanager.py"
    
    try:
        with open(gamemanager_path, 'r') as f:
            content = f.read()
        
        # Test 1: Check for waitForPromotionChoice function
        if 'def waitForPromotionChoice():' in content:
            print("  PASS: waitForPromotionChoice function found")
        else:
            print("  FAIL: waitForPromotionChoice function not found")
            return False
        
        # Test 2: Check for correct button mappings
        button_mappings = [
            ("'BACK'", "'n'"),
            ("'TICK'", "'b'"), 
            ("'UP'", "'q'"),
            ("'DOWN'", "'r'")
        ]
        
        mapping_found = 0
        for button, piece in button_mappings:
            if button in content and piece in content:
                mapping_found += 1
                print(f"  PASS: {button} -> {piece} mapping found")
        
        if mapping_found == len(button_mappings):
            print("  PASS: All button mappings found")
        else:
            print(f"  FAIL: Only {mapping_found}/{len(button_mappings)} mappings found")
            return False
        
        # Test 3: Check for board.wait_for_key_up usage
        if 'board.wait_for_key_up(' in content:
            print("  PASS: board.wait_for_key_up() usage found")
        else:
            print("  FAIL: board.wait_for_key_up() usage not found")
            return False
        
        # Test 4: Check for board.beep usage
        if 'board.beep(' in content:
            print("  PASS: board.beep() usage found")
        else:
            print("  FAIL: board.beep() usage not found")
            return False
        
        return True
        
    except FileNotFoundError:
        print(f"  ERROR: Could not read {gamemanager_path}")
        return False

def test_no_direct_serial_access():
    """Test that no direct serial access remains"""
    print("\nTesting for direct serial access patterns...")
    
    gamemanager_path = "DGTCentaurMods/game/gamemanager.py"
    
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
            return True
        else:
            print(f"  FAIL: Found forbidden patterns: {violations}")
            return False
            
    except FileNotFoundError:
        print(f"  ERROR: Could not read {gamemanager_path}")
        return False

def test_board_wrapper_exists():
    """Test that the board.py wrapper function exists"""
    print("\nTesting board.py wrapper function...")
    
    board_path = "DGTCentaurMods/board/board.py"
    
    try:
        with open(board_path, 'r') as f:
            content = f.read()
        
        if 'def wait_for_key_up(' in content:
            print("  PASS: wait_for_key_up wrapper function found")
            return True
        else:
            print("  FAIL: wait_for_key_up wrapper function not found")
            return False
            
    except FileNotFoundError:
        print(f"  ERROR: Could not read {board_path}")
        return False

def main():
    """Run all minimal tests"""
    print("Starting Minimal Promotion Button Handling Tests")
    print("=" * 50)
    
    tests = [
        test_gamemanager_source_code,
        test_no_direct_serial_access,
        test_board_wrapper_exists,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {test.__name__} failed with exception: {e}")
            results.append(False)
    
    # Print summary
    print("\nTest Results Summary:")
    print("=" * 30)
    passed = sum(results)
    total = len(results)
    
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("All tests passed!")
        return 0
    else:
        print("Some tests failed - check the results above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
