#!/usr/bin/env python3
"""
Test script to verify if display() function blocks and waits for hardware completion.

This script should be run on the Raspberry Pi with the actual hardware connected.
It measures the duration of display() calls to determine if they block correctly.

Expected behavior:
- display() should take 1.5-2.0 seconds (full refresh time)
- If it returns faster (< 1.0s), it's not blocking correctly
"""

import time
from ctypes import CDLL, c_int
import pathlib
import sys

def test_display_blocking():
    """Test if display() blocks until hardware refresh completes."""
    lib_path = pathlib.Path("/opt/DGTCentaurMods/display/epaperDriver.so")
    if not lib_path.exists():
        lib_path = pathlib.Path("DGTCentaurMods/opt/DGTCentaurMods/display/epaperDriver.so")
    
    if not lib_path.exists():
        print(f"ERROR: {lib_path} not found")
        print("This test must be run on the Raspberry Pi with the driver available.")
        return False
    
    print(f"Loading driver: {lib_path}")
    try:
        dll = CDLL(str(lib_path))
        dll.readBusy.argtypes = []
        dll.readBusy.restype = c_int
        
        print("\n=== Test: Measuring display() blocking behavior ===")
        dll.openDisplay()
        print("Driver opened successfully")
        
        # CRITICAL: Initialize display hardware before use
        # This is required - display won't work without reset() and init()
        print("\nInitializing display hardware...")
        print("  Calling reset()...")
        dll.reset()
        print("  Calling init()...")
        dll.init()
        print("  Display initialized successfully")
        
        # Create a minimal test image (128x296, all white)
        # Image size: 128 * 296 / 8 = 4736 bytes
        test_data = bytes([0xFF] * 4736)
        
        print("\nTest 1: Full refresh with all-white image")
        print("Calling display() with test image...")
        start = time.time()
        dll.display(test_data)
        elapsed = time.time() - start
        
        print(f"\nResult: display() returned after {elapsed:.3f} seconds")
        
        if elapsed < 0.5:
            print("❌ CRITICAL: display() returned too quickly (< 0.5s)")
            print("   This indicates display() is NOT blocking correctly.")
            print("   The hardware refresh did not complete.")
            result = False
        elif elapsed < 1.0:
            print("⚠️  WARNING: display() returned quickly (< 1.0s)")
            print("   Expected 1.5-2.0s for full refresh.")
            print("   display() may not be waiting for hardware completion.")
            result = False
        elif elapsed >= 1.5:
            print("✅ SUCCESS: display() appears to block correctly (>= 1.5s)")
            print("   This matches expected full refresh time (1.5-2.0s).")
            result = True
        else:
            print("⚠️  CAUTION: display() duration is between 1.0-1.5s")
            print("   This is unusual - may indicate partial blocking.")
            result = None
        
        # Test 2: Check readBusy() behavior
        print("\n=== Test 2: Checking readBusy() return values ===")
        print("Calling readBusy() 10 times...")
        values = []
        for i in range(10):
            val = dll.readBusy()
            values.append(val)
            print(f"  readBusy() call #{i+1}: {val} (0x{val:08x}, masked: {val & 0x01})")
        
        unique_values = set(values)
        if len(unique_values) == 1 and list(unique_values)[0] in [0, 1]:
            print("✅ readBusy() returns consistent values (0 or 1)")
        elif all(v & 0x01 in [0, 1] for v in values):
            print("⚠️  readBusy() returns garbage values, but masked values are 0/1")
        else:
            print("❌ readBusy() returns inconsistent garbage values")
        
        dll.closeDisplay()
        print("\n=== Test Complete ===")
        return result
        
    except OSError as e:
        if "mach-o" in str(e).lower():
            print("ERROR: Cannot load ARM binary on macOS.")
            print("This test must be run on the Raspberry Pi.")
        else:
            print(f"ERROR loading driver: {e}")
        return None
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    result = test_display_blocking()
    sys.exit(0 if result is True else 1)

