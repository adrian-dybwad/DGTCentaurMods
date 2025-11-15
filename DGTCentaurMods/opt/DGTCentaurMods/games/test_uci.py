#!/usr/bin/env python3
"""Test script for games/uci.py"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from games import uci
    print("✓ Successfully imported uci")
except Exception as e:
    print(f"✗ Failed to import uci: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test basic instantiation (without actually starting engines)
try:
    handler = uci.UCIHandler("white", "stockfish_pi", "Default")
    print("✓ Successfully created UCIHandler instance")
except Exception as e:
    print(f"✗ Failed to create UCIHandler: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test methods exist
required_methods = [
    '_load_engine_options', '_initialize_engines', '_cleanup_engines',
    '_event_callback', '_move_callback', '_takeback_callback', '_key_callback',
    '_play_computer_move', '_draw_board', '_handle_game_over', 'start'
]

for method in required_methods:
    if hasattr(handler, method):
        print(f"✓ Method {method} exists")
    else:
        print(f"✗ Method {method} MISSING")
        sys.exit(1)

print("\n✓ All basic tests passed!")

