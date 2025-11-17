#!/usr/bin/env python3
"""
Simple test of old epaperDriver.so using the exact same method as the working code.
"""

import sys
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

# Use the exact same approach as the working NativeDriver
from ctypes import CDLL, c_uint8
from PIL import Image
import time

def test_old_driver_simple():
    """Test old driver using exact same method as NativeDriver."""
    print("=" * 60)
    print("Testing OLD epaperDriver.so (NativeDriver method)")
    print("=" * 60)
    
    # Find epaperDriver.so using same path as NativeDriver
    lib_path = Path(__file__).resolve().parents[1] / "display" / "epaperDriver.so"
    
    if not lib_path.exists():
        print(f"ERROR: epaperDriver.so not found at {lib_path}")
        return False
    
    print(f"Found library at: {lib_path}")
    
    try:
        print("\n1. Loading library and opening display...")
        dll = CDLL(str(lib_path))
        dll.openDisplay()
        print("   ✓ Display opened")
        
        print("\n2. Resetting display...")
        dll.reset()
        print("   ✓ Reset complete")
        time.sleep(0.1)
        
        print("\n3. Initializing display...")
        dll.init()
        print("   ✓ Initialization complete")
        time.sleep(0.1)
        
        print("\n4. Creating BLACK image using NativeDriver._convert() method...")
        # Use exact same conversion as NativeDriver._convert()
        width, height = 128, 296
        img = Image.new('1', (width, height), 0)  # Black
        buf = [0xFF] * (int(width / 8) * height)
        mono = img.convert("1")
        pixels = mono.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:
                    buf[int((x + y * width) / 8)] &= ~(0x80 >> (x % 8))
        image_data = bytes(buf)
        image_data_ptr = (c_uint8 * len(image_data)).from_buffer_copy(image_data)
        print(f"   ✓ Image created: {len(image_data)} bytes")
        
        print("\n5. Calling display() (this should take ~2 seconds)...")
        print("   WATCH THE DISPLAY NOW!")
        start = time.time()
        dll.display(image_data_ptr)
        elapsed = time.time() - start
        print(f"   ✓ display() returned in {elapsed:.2f}s")
        
        if elapsed < 1.0:
            print("   ⚠️  WARNING: Too fast - display may not have updated")
        elif elapsed > 5.0:
            print("   ⚠️  WARNING: Too slow - may have hung")
        else:
            print("   ✓ Timing looks correct")
        
        print("\n6. Did the display show a BLACK screen?")
        print("   (Look carefully - it may be subtle)")
        print("   Type 'yes' if you saw black, or 'no' if nothing changed...")
        response = input().strip().lower()
        
        if response == 'yes':
            print("\n✅ OLD DRIVER WORKS! The display hardware is functional.")
            print("   The issue is with the new driver's configuration.")
            return True
        else:
            print("\n❌ OLD DRIVER ALSO FAILED")
            print("   This suggests a hardware issue or the display needs different initialization.")
            print("\n   Trying white screen test...")
            
            print("\n7. Creating WHITE image...")
            img = Image.new('1', (width, height), 255)  # White
            buf = [0xFF] * (int(width / 8) * height)
            mono = img.convert("1")
            pixels = mono.load()
            for y in range(height):
                for x in range(width):
                    if pixels[x, y] == 0:
                        buf[int((x + y * width) / 8)] &= ~(0x80 >> (x % 8))
            image_data = bytes(buf)
            image_data_ptr = (c_uint8 * len(image_data)).from_buffer_copy(image_data)
            
            print("\n8. Calling display() with white image...")
            start = time.time()
            dll.display(image_data_ptr)
            elapsed = time.time() - start
            print(f"   ✓ display() returned in {elapsed:.2f}s")
            
            print("\n9. Did the display show a WHITE screen?")
            response = input().strip().lower()
            
            if response == 'yes':
                print("\n✅ OLD DRIVER WORKS! The display hardware is functional.")
                return True
            else:
                print("\n❌ OLD DRIVER COMPLETELY FAILED")
                print("   Possible issues:")
                print("   - Display not powered")
                print("   - Display not connected")
                print("   - Hardware failure")
                print("   - Wrong display model")
                return False
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            print("\n10. Shutting down...")
            dll.powerOffDisplay()
            print("   ✓ Shutdown complete")
        except:
            pass

if __name__ == "__main__":
    result = test_old_driver_simple()
    if result:
        print("\n" + "=" * 60)
        print("NEXT STEPS:")
        print("=" * 60)
        print("Since the old driver works, the new driver needs:")
        print("1. Correct GPIO pin configuration")
        print("2. Correct SPI device selection")
        print("3. Correct initialization sequence")
        print("4. Correct image data format")
    else:
        print("\n" + "=" * 60)
        print("TROUBLESHOOTING:")
        print("=" * 60)
        print("If the old driver also fails, check:")
        print("1. Is the display powered?")
        print("2. Are all connections secure?")
        print("3. Is this the correct display model?")
        print("4. Try power cycling the device")

