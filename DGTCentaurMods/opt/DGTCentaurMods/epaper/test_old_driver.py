#!/usr/bin/env python3
"""
Test the old epaperDriver.so to verify the display works and compare behavior.
"""

import sys
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

from ctypes import CDLL, c_uint8
from PIL import Image

def test_old_driver():
    """Test the old driver to verify display works."""
    print("=" * 60)
    print("Testing OLD epaperDriver.so")
    print("=" * 60)
    
    # Find epaperDriver.so
    possible_paths = [
        parent_dir / "display" / "epaperDriver.so",
        Path("/opt/DGTCentaurMods/epaper/epaperDriver.so"),
    ]
    
    lib_path = None
    for path in possible_paths:
        if path.exists():
            lib_path = path
            break
    
    if not lib_path:
        print("ERROR: epaperDriver.so not found")
        return False
    
    print(f"Found library at: {lib_path}")
    
    try:
        print("\n1. Loading library...")
        dll = CDLL(str(lib_path))
        print("   ✓ Library loaded")
        
        print("\n2. Opening display...")
        dll.openDisplay()
        print("   ✓ Display opened")
        
        print("\n3. Resetting display...")
        dll.reset()
        print("   ✓ Reset complete")
        
        print("\n4. Initializing display...")
        dll.init()
        print("   ✓ Initialization complete")
        
        print("\n5. Creating BLACK test image...")
        # Create black image using old driver's conversion method
        width, height = 128, 296
        img = Image.new('1', (width, height), 0)  # Black
        buf = [0xFF] * (int(width / 8) * height)
        pixels = img.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:
                    buf[int((x + y * width) / 8)] &= ~(0x80 >> (x % 8))
        image_data = bytes(buf)
        image_data_ptr = (c_uint8 * len(image_data)).from_buffer_copy(image_data)
        print(f"   ✓ Image created: {len(image_data)} bytes")
        
        print("\n6. Displaying image (this should take ~2 seconds)...")
        import time
        start = time.time()
        dll.display(image_data_ptr)
        elapsed = time.time() - start
        print(f"   ✓ Display complete in {elapsed:.2f}s")
        
        if elapsed < 1.0:
            print("   ⚠️  WARNING: Display returned too quickly!")
        elif elapsed > 5.0:
            print("   ⚠️  WARNING: Display took too long!")
        else:
            print("   ✓ Timing looks correct")
        
        print("\n7. Did you see a BLACK screen?")
        print("   Press Enter to continue...")
        input()
        
        print("\n8. Creating WHITE test image...")
        img = Image.new('1', (width, height), 255)  # White
        buf = [0xFF] * (int(width / 8) * height)
        pixels = img.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:
                    buf[int((x + y * width) / 8)] &= ~(0x80 >> (x % 8))
        image_data = bytes(buf)
        image_data_ptr = (c_uint8 * len(image_data)).from_buffer_copy(image_data)
        
        print("\n9. Displaying white image...")
        start = time.time()
        dll.display(image_data_ptr)
        elapsed = time.time() - start
        print(f"   ✓ Display complete in {elapsed:.2f}s")
        
        print("\n10. Did you see a WHITE screen?")
        print("    Press Enter to continue...")
        input()
        
        print("\n11. Shutting down...")
        dll.powerOffDisplay()
        print("   ✓ Shutdown complete")
        
        print("\n" + "=" * 60)
        print("OLD DRIVER TEST COMPLETE")
        print("=" * 60)
        print("\nIf you saw black and white screens, the display hardware works!")
        print("The issue is with the new driver's pin configuration or initialization.")
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_old_driver()

