#!/usr/bin/env python3
"""
Safe test script to determine displayPartial() function signature.

This script tests each signature in a separate subprocess to avoid
killing the main process when a segfault occurs.

Run this on the Raspberry Pi with hardware connected.
"""

import sys
import pathlib
import subprocess
import os

# Create individual test scripts for each signature
test_script_template = '''#!/usr/bin/env python3
import sys
import pathlib
from ctypes import CDLL, c_int, c_uint8, POINTER
from PIL import Image, ImageDraw

lib_path = pathlib.Path("{lib_path}")
dll = CDLL(str(lib_path))
dll.openDisplay()
dll.init()

# Create test image
test_image = Image.new("1", (12, 12), 255)
draw = ImageDraw.Draw(test_image)
draw.ellipse((2, 2, 10, 10), fill=0)

# Convert to bytes
width, height = test_image.size
bytes_per_row = (width + 7) // 8
buf = [0xFF] * (bytes_per_row * height)
pixels = test_image.load()

for y in range(height):
    for x in range(width):
        if pixels[x, y] == 0:
            byte_index = y * bytes_per_row + (x // 8)
            bit_position = x % 8
            buf[byte_index] &= ~(0x80 >> bit_position)

image_data = bytes(buf)
image_data_ptr = (c_uint8 * len(image_data)).from_buffer_copy(image_data)

# Test coordinates
x1, y1 = 58, 142
x2, y2 = 70, 154
width, height = 12, 12

# Configure function signature
{signature_setup}

# Call function
try:
    {function_call}
    print("SUCCESS: No crash!")
    sys.exit(0)
except Exception as e:
    print(f"ERROR: {{e}}")
    sys.exit(1)
'''

# Find library path
possible_paths = [
    pathlib.Path("/opt/DGTCentaurMods/epaper/epaperDriver.so"),
    pathlib.Path(__file__).resolve().parents[2] / "DGTCentaurMods/opt/DGTCentaurMods/epaper/epaperDriver.so",
]

lib_path = None
for path in possible_paths:
    if path.exists():
        lib_path = path
        break

if lib_path is None:
    print("ERROR: epaperDriver.so not found")
    sys.exit(1)

lib_path_str = str(lib_path.resolve())

# Test signatures
tests = [
    {
        "name": "displayPartial(x1, y1, x2, y2, image_data)",
        "setup": "dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, POINTER(c_uint8)]\ndll.displayPartial.restype = None",
        "call": "dll.displayPartial(x1, y1, x2, y2, image_data_ptr)"
    },
    {
        "name": "displayPartial(x, y, width, height, image_data)",
        "setup": "dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, POINTER(c_uint8)]\ndll.displayPartial.restype = None",
        "call": "dll.displayPartial(x1, y1, width, height, image_data_ptr)"
    },
    {
        "name": "displayPartial(image_data, x1, y1, x2, y2)",
        "setup": "dll.displayPartial.argtypes = [POINTER(c_uint8), c_int, c_int, c_int, c_int]\ndll.displayPartial.restype = None",
        "call": "dll.displayPartial(image_data_ptr, x1, y1, x2, y2)"
    },
    {
        "name": "displayPartial(image_data, x, y, width, height)",
        "setup": "dll.displayPartial.argtypes = [POINTER(c_uint8), c_int, c_int, c_int, c_int]\ndll.displayPartial.restype = None",
        "call": "dll.displayPartial(image_data_ptr, x1, y1, width, height)"
    },
    {
        "name": "displayPartial(x1, y1, x2, y2, width, height, image_data)",
        "setup": "dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, c_int, c_int, POINTER(c_uint8)]\ndll.displayPartial.restype = None",
        "call": "dll.displayPartial(x1, y1, x2, y2, width, height, image_data_ptr)"
    },
    {
        "name": "displayPartial(x0, x1, y0, y1, image_data) - like displayRegion",
        "setup": "dll.displayPartial.argtypes = [c_int, c_int, c_int, c_int, POINTER(c_uint8)]\ndll.displayPartial.restype = None",
        "call": "dll.displayPartial(x1, x2, y1, y2, image_data_ptr)"
    },
]

print("Testing displayPartial() function signatures")
print("=" * 60)
print(f"Library: {lib_path_str}")
print(f"Test region: (58, 142) to (70, 154), Image: 12x12 pixels")
print("=" * 60)
print()

results = []

for i, test in enumerate(tests, 1):
    print(f"Test {i}: {test['name']}")
    
    # Create temporary test script
    test_script = test_script_template.format(
        lib_path=lib_path_str,
        signature_setup=test['setup'],
        function_call=test['call']
    )
    
    # Write to temp file
    temp_file = f"/tmp/test_displayPartial_{i}.py"
    with open(temp_file, 'w') as f:
        f.write(test_script)
    os.chmod(temp_file, 0o755)
    
    # Run in subprocess
    try:
        result = subprocess.run(
            [sys.executable, temp_file],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            print(f"  ✅ SUCCESS: {result.stdout.strip()}")
            print(f"  ⚠️  Check display - if you see a partial update, this is the correct signature!")
            results.append((i, test['name'], "SUCCESS"))
        else:
            if "Segmentation fault" in result.stderr or result.returncode == -11:
                print(f"  ❌ Segmentation fault - signature incorrect")
                results.append((i, test['name'], "SEGFAULT"))
            else:
                print(f"  ❌ Error: {result.stderr.strip()}")
                results.append((i, test['name'], "ERROR"))
    except subprocess.TimeoutExpired:
        print(f"  ⏱️  Timeout - function may be hanging")
        results.append((i, test['name'], "TIMEOUT"))
    except Exception as e:
        print(f"  ❌ Exception: {e}")
        results.append((i, test['name'], "EXCEPTION"))
    
    # Clean up
    try:
        os.remove(temp_file)
    except:
        pass
    
    print()

# Summary
print("=" * 60)
print("SUMMARY")
print("=" * 60)
for i, name, status in results:
    status_symbol = "✅" if status == "SUCCESS" else "❌"
    print(f"{status_symbol} Test {i}: {status}")

successful = [r for r in results if r[2] == "SUCCESS"]
if successful:
    print(f"\n✅ {len(successful)} signature(s) didn't crash!")
    print("Check the display to see which one actually shows a partial update.")
    print("The one that shows a partial update in the correct location is the correct signature.")
else:
    print("\n❌ All signatures caused crashes or errors.")
    print("displayPartial() may:")
    print("  1. Have a completely different signature")
    print("  2. Require additional setup/initialization")
    print("  3. Not support partial-width refreshes (same as displayRegion)")
    print("  4. Be broken or unused in this library version")

print("\nCleaning up...")
# Final cleanup - put display to sleep
try:
    from ctypes import CDLL
    dll = CDLL(str(lib_path))
    dll.openDisplay()
    dll.sleepDisplay()
    dll.powerOffDisplay()
except:
    pass

print("Done!")

