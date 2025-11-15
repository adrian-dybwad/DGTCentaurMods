#!/usr/bin/env python3
"""Test script for games/manager.py"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from games import manager
    print("✓ Successfully imported manager")
except Exception as e:
    print(f"✗ Failed to import manager: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test basic instantiation
try:
    gm = manager.GameManager()
    print("✓ Successfully created GameManager instance")
except Exception as e:
    print(f"✗ Failed to create GameManager: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test methods exist
required_methods = [
    'subscribe_event', 'subscribe_move', 'subscribe_key', 'subscribe_takeback',
    'set_game_info', 'get_board', 'get_fen', 'set_computer_move', 
    'reset_move_state', 'start', 'stop', 'resign_game', 'draw_game'
]

for method in required_methods:
    if hasattr(gm, method):
        print(f"✓ Method {method} exists")
    else:
        print(f"✗ Method {method} MISSING")
        sys.exit(1)

# Test constants
required_constants = [
    'EVENT_NEW_GAME', 'EVENT_BLACK_TURN', 'EVENT_WHITE_TURN',
    'EVENT_REQUEST_DRAW', 'EVENT_RESIGN_GAME'
]

for const in required_constants:
    if hasattr(manager, const):
        print(f"✓ Constant {const} exists")
    else:
        print(f"✗ Constant {const} MISSING")
        sys.exit(1)

print("\n✓ All basic tests passed!")

