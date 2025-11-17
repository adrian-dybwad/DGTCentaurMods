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

# Clear display first with full white refresh
print("Clearing display...")
clear_image = Image.new("1", (128, 296), 255)  # White
width, height = clear_image.size
bytes_per_row = (width + 7) // 8
clear_buf = [0xFF] * (bytes_per_row * height)
clear_data = bytes(clear_buf)
clear_data_ptr = (c_uint8 * len(clear_data)).from_buffer_copy(clear_data)
dll.display(clear_data_ptr)

# Create test image - larger black square for visibility
test_size = 20  # 20x20 pixels - larger and easier to see
test_image = Image.new("1", (test_size, test_size), 255)  # White background
draw = ImageDraw.Draw(test_image)
# Draw a black square (leave 1 pixel border for visibility)
draw.rectangle((1, 1, test_size-2, test_size-2), fill=0)  # Black square

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

# Test coordinates - center of screen, larger area
x1, y1 = 54, 138  # Center minus half of test_size
x2, y2 = 74, 158  # Center plus half of test_size
width, height = test_size, test_size

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

# Test signatures - only test the ones that didn't crash
tests = [
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
]

print("Testing displayPartial() function signatures")
print("=" * 60)
print(f"Library: {lib_path_str}")
print(f"Test region: (54, 138) to (74, 158), Image: 20x20 pixels (black square)")
print("Display will be cleared first, then each successful signature will be tested")
print("=" * 60)
print()

results = []

for i, test in enumerate(tests, 1):
    print(f"Test {i}: {test['name']}")
    print(f"  Looking for a 20x20 black square at center of screen (around x=54-74, y=138-158)")
    
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
            timeout=10  # Increased timeout for display refresh
        )
        
        if result.returncode == 0:
            print(f"  ✅ SUCCESS: {result.stdout.strip()}")
            print(f"  👀 CHECK DISPLAY NOW - Do you see a black square in the center?")
            print(f"  📍 Expected location: center of screen (x=54-74, y=138-158)")
            input(f"  Press Enter after checking the display, then we'll test the next signature...")
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

