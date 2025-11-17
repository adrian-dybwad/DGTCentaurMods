#!/usr/bin/env python3
"""
Test script to determine displayPartial() function signature.

This script attempts to call displayPartial() with various common signatures
to determine which one works. Run this on the Raspberry Pi with hardware connected.

WARNING: Incorrect function calls may cause crashes or display issues.
Test carefully and monitor the display output.
"""

import sys
import pathlib
import signal
from ctypes import CDLL, c_int, c_uint8, POINTER, Structure, byref
from PIL import Image

# Handle segmentation faults gracefully
def segfault_handler(signum, frame):
    print("  ❌ Segmentation fault - signature is incorrect")
    raise SystemExit("Segfault detected")

signal.signal(signal.SIGSEGV, segfault_handler)

# Locate the library (try multiple possible paths)
possible_paths = [
    pathlib.Path("/opt/DGTCentaurMods/epaper/epaperDriver.so"),  # Production path
    pathlib.Path(__file__).resolve().parents[2] / "DGTCentaurMods/opt/DGTCentaurMods/epaper/epaperDriver.so",  # Dev path
    pathlib.Path(__file__).resolve().parent.parent.parent / "DGTCentaurMods/opt/DGTCentaurMods/epaper/epaperDriver.so",  # Alternative dev path
]

lib_path = None
for path in possible_paths:
    if path.exists():
        lib_path = path
        break

if lib_path is None:
    print(f"ERROR: epaperDriver.so not found in any of these locations:")
    for path in possible_paths:
        print(f"  - {path}")
    sys.exit(1)

print(f"Loading library: {lib_path}")
dll = CDLL(str(lib_path))
dll.openDisplay()

# Initialize display
print("Initializing display...")
dll.init()

# Create a small test image (12x12 pixels - ball size)
test_image = Image.new("1", (12, 12), 255)  # White background
from PIL import ImageDraw
draw = ImageDraw.Draw(test_image)
draw.ellipse((2, 2, 10, 10), fill=0)  # Black circle

# Convert to bytes (same format as driver.py)
width, height = test_image.size
bytes_per_row = (width + 7) // 8
buf = [0xFF] * (bytes_per_row * height)
pixels = test_image.load()

for y in range(height):
    for x in range(width):
        if pixels[x, y] == 0:  # Black pixel
            byte_index = y * bytes_per_row + (x // 8)
            bit_position = x % 8
            buf[byte_index] &= ~(0x80 >> bit_position)

image_data = bytes(buf)
image_data_ptr = (c_uint8 * len(image_data)).from_buffer_copy(image_data)

# Test region (small area in center of screen)
x1, y1 = 58, 142  # Center of 128x296 display
x2, y2 = 70, 154  # x1+12, y1+12

print(f"\nTesting displayPartial() with different signatures...")
print(f"Test region: ({x1}, {y1}) to ({x2}, {y2})")
print(f"Image size: {width}x{height} pixels")
print()

# Signature 1: displayPartial(x1, y1, x2, y2, image_data)
print("Test 1: displayPartial(x1, y1, x2, y2, image_data)")
try:
    dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, POINTER(c_uint8)]
    dll.displayPartial.restype = None
    dll.displayPartial(x1, y1, x2, y2, image_data_ptr)
    print("  ✅ No crash - signature might be correct!")
    print("  Check display to see if partial update appeared")
    print("  If you see a partial update, this is the correct signature!")
except (SystemExit, KeyboardInterrupt):
    raise
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\nPress Enter to continue to next test (or Ctrl+C to exit)...")
try:
    input()
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)

# Signature 2: displayPartial(x, y, width, height, image_data)
print("\nTest 2: displayPartial(x, y, width, height, image_data)")
try:
    dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, POINTER(c_uint8)]
    dll.displayPartial.restype = None
    dll.displayPartial(x1, y1, width, height, image_data_ptr)
    print("  ✅ No crash - signature might be correct!")
    print("  Check display to see if partial update appeared")
    print("  If you see a partial update, this is the correct signature!")
except (SystemExit, KeyboardInterrupt):
    raise
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\nPress Enter to continue to next test (or Ctrl+C to exit)...")
try:
    input()
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)

# Signature 3: displayPartial(image_data, x1, y1, x2, y2)
print("\nTest 3: displayPartial(image_data, x1, y1, x2, y2)")
try:
    dll.displayPartial.argtypes = [POINTER(c_uint8), c_int, c_int, c_int, c_int]
    dll.displayPartial.restype = None
    dll.displayPartial(image_data_ptr, x1, y1, x2, y2)
    print("  ✅ No crash - signature might be correct!")
    print("  Check display to see if partial update appeared")
    print("  If you see a partial update, this is the correct signature!")
except (SystemExit, KeyboardInterrupt):
    raise
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\nPress Enter to continue to next test (or Ctrl+C to exit)...")
try:
    input()
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)

# Signature 4: displayPartial(image_data, x, y, width, height)
print("\nTest 4: displayPartial(image_data, x, y, width, height)")
try:
    dll.displayPartial.argtypes = [POINTER(c_uint8), c_int, c_int, c_int, c_int]
    dll.displayPartial.restype = None
    dll.displayPartial(image_data_ptr, x1, y1, width, height)
    print("  ✅ No crash - signature might be correct!")
    print("  Check display to see if partial update appeared")
    print("  If you see a partial update, this is the correct signature!")
except (SystemExit, KeyboardInterrupt):
    raise
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\nPress Enter to continue to next test (or Ctrl+C to exit)...")
try:
    input()
except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)

# Signature 5: displayPartial(x1, y1, x2, y2, width, height, image_data)
print("\nTest 5: displayPartial(x1, y1, x2, y2, width, height, image_data)")
try:
    dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, c_int, c_int, POINTER(c_uint8)]
    dll.displayPartial.restype = None
    dll.displayPartial(x1, y1, x2, y2, width, height, image_data_ptr)
    print("  ✅ No crash - signature might be correct!")
    print("  Check display to see if partial update appeared")
    print("  If you see a partial update, this is the correct signature!")
except (SystemExit, KeyboardInterrupt):
    raise
except Exception as e:
    print(f"  ❌ Error: {e}")

# Try comparing with displayRegion signature - maybe it's similar?
print("\n" + "=" * 60)
print("Additional test: Comparing with displayRegion signature")
print("=" * 60)
print("\nNote: displayRegion takes (y0, y1, image_data)")
print("Maybe displayPartial takes similar but with x coordinates?")
print("\nTest 6: displayPartial(x0, x1, y0, y1, image_data) - like displayRegion")
try:
    dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, POINTER(c_uint8)]
    dll.displayPartial.restype = None
    # Try x coordinates first, then y (like displayRegion does y0, y1)
    dll.displayPartial(x1, x2, y1, y2, image_data_ptr)
    print("  ✅ No crash - signature might be correct!")
    print("  Check display to see if partial update appeared")
except (SystemExit, KeyboardInterrupt):
    raise
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print("Testing complete!")
print("\nIf any test showed a partial update on the display, that signature is likely correct.")
print("If all tests crashed or showed nothing, displayPartial() may:")
print("  1. Have a different signature than tested")
print("  2. Require additional setup/initialization")
print("  3. Have the same limitation as displayRegion() (full-width only)")
print("  4. Not work as expected")

# Cleanup
dll.sleepDisplay()
dll.powerOffDisplay()
print("\nDisplay put to sleep.")

