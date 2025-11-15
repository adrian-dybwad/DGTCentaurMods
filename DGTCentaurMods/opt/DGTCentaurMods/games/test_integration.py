#!/usr/bin/env python3
"""Integration test to verify manager and uci work together"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("Testing games package integration...")
print("=" * 50)

# Test 1: Can we import?
try:
    from games import manager, uci
    print("✓ Imports successful")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Can we create instances?
try:
    gm = manager.get_manager()
    print("✓ Manager instance created")
    
    handler = uci.UCIHandler("white", "stockfish_pi", "Default")
    print("✓ UCI handler instance created")
except Exception as e:
    print(f"✗ Instance creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Can we subscribe?
try:
    event_count = [0]
    move_count = [0]
    
    def test_event(e):
        event_count[0] += 1
        print(f"  Event received: {e}")
    
    def test_move(m):
        move_count[0] += 1
        print(f"  Move received: {m}")
    
    def test_key(k):
        print(f"  Key received: {k}")
    
    gm.subscribe_event(test_event)
    gm.subscribe_move(test_move)
    gm.subscribe_key(test_key)
    print("✓ Subscriptions successful")
except Exception as e:
    print(f"✗ Subscription failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Check constants
try:
    assert hasattr(manager, 'EVENT_NEW_GAME')
    assert hasattr(manager, 'EVENT_WHITE_TURN')
    assert hasattr(manager, 'EVENT_BLACK_TURN')
    print("✓ Constants exist")
except Exception as e:
    print(f"✗ Constants check failed: {e}")
    sys.exit(1)

print("\n" + "=" * 50)
print("All basic integration tests passed!")
print("\nNote: Full testing requires:")
print("  - Hardware board connection")
print("  - Chess engine binaries")
print("  - Database setup")

