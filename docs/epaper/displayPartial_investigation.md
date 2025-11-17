# displayPartial() Function Investigation

## Summary

Investigation into the `displayPartial()` function found in `epaperDriver.so` to determine if it supports partial-width refreshes (x/y coordinates) instead of full-width row refreshes.

## Findings

### 1. Function Existence Confirmed

The library contains three display-related functions:
- `display()` - Full screen refresh
- `displayRegion(y0, y1, image)` - Partial refresh by rows only (currently used)
- `displayPartial()` - **Unused function that may support x/y coordinates**

### 2. Library Symbols

From `nm -D` and `objdump -T`:
```
000017c0 T displayPartial
000013a8 T display
0000190c T displayRegion
```

From `strings` output, also found:
- `unsetRegion` - May be related to setting/clearing regions

### 3. Current Usage

**Currently Used:**
- `displayRegion(y0, y1, image)` - Only takes y coordinates, refreshes full-width rows

**Not Used:**
- `displayPartial()` - Signature unknown, may support x/y coordinates

### 4. Proxy Implementation Reference

Found in `build/vm-setup/epaper_proxy_client.py`:
```python
def DisplayPartial(self, image):
    """Display partial update"""
    send_display_update(image)
```

However, this is a proxy implementation that just forwards the image - it doesn't reveal the actual C library signature.

### 5. Related Libraries

Other ePaper libraries (like GxEPD2) use patterns like:
```cpp
display.setPartialWindow(x, y, width, height);
```

This suggests `displayPartial()` might follow a similar pattern, possibly:
- `displayPartial(x1, y1, x2, y2, image_data)`
- `displayPartial(x, y, width, height, image_data)`
- Or similar coordinate-based signature

## Next Steps

To determine the exact function signature, you would need to:

1. **Check C Source Code** (if available):
   - Look for the source files that built `epaperDriver.so`
   - Check function definitions and documentation

2. **Reverse Engineering**:
   - Use tools like `objdump -d` to disassemble the function
   - Analyze the assembly to determine parameter types and count
   - Test with different signatures using ctypes

3. **Trial and Error** (Risky):
   - Try common signatures:
     - `displayPartial(x1, y1, x2, y2, image_data)`
     - `displayPartial(x, y, width, height, image_data)`
     - `displayPartial(x1, y1, x2, y2, width, height, image_data)`
   - Test on hardware to see if it works
   - **Warning**: Incorrect calls could potentially cause issues

4. **Contact Original Developer**:
   - If you have access to the original developer or documentation
   - Ask for the function signature and usage examples

5. **UC8151 Datasheet**:
   - Check if the UC8151 controller supports windowed updates
   - The controller may support partial-width refreshes even if the C library doesn't expose it easily

## Implementation Plan (If Signature is Found)

If `displayPartial()` supports x/y coordinates:

1. **Update `driver.py`**:
   ```python
   def partial_refresh(self, region: Region, image: Image.Image) -> None:
       """Perform a partial screen refresh with x/y coordinates."""
       # Convert region to hardware coordinates
       x1, y1 = region.x1, region.y1
       x2, y2 = region.x2, region.y2
       
       # Rotate 180 degrees to match hardware orientation
       rotated = image.transpose(Image.ROTATE_180)
       
       # Call displayPartial with coordinates
       self._dll.displayPartial(x1, y1, x2, y2, self._convert_to_bytes(rotated))
   ```

2. **Update `regions.py`**:
   ```python
   def expand_to_controller_alignment(region: Region, width: int, height: int) -> Region:
       """Expand region to align with controller requirements."""
       row_height = 8
       # Only expand vertically to 8-pixel row boundaries
       y1 = max(0, (region.y1 // row_height) * row_height)
       y2 = min(height, ((region.y2 + row_height - 1) // row_height) * row_height)
       
       # Keep original x coordinates (no horizontal expansion needed)
       return Region(region.x1, y1, region.x2, y2)
   ```

3. **Update `refresh_scheduler.py`**:
   - Change `partial_refresh()` call to pass the region instead of just y0, y1
   - Update driver interface to accept region parameter

## Documentation Sources Found

### 1. Library Origin
- **Vendor**: Waveshare (Good Display GDEH029A1 panel)
- **Controller**: UC8151
- **Current Version**: September 9, 2023 (commit efc8b99)
- **Newer Version Available**: `waveshare-epaper` v1.3.0 (July 2, 2024) on PyPI

### 2. Potential Documentation Sources
- **Waveshare GitHub**: https://github.com/waveshare/e-Paper
- **Waveshare Wiki**: https://www.waveshare.com/wiki/ (e-Paper Driver HAT, development guides)
- **PyPI Package**: https://pypi.org/project/waveshare-epaper/ (v1.3.0)
- **UC8151 Datasheet**: Register 0x44/0x45 for partial refresh window coordinates

### 3. Related Libraries with displayPartial
- **Adafruit CircuitPython UC8151D**: Has `displayPartial` function with documentation
- **DeviceScript UC8151 Driver**: Another implementation reference
- **GxEPD2 Library**: Uses `setPartialWindow(x, y, width, height)` pattern

### 4. Hardware Specifications
- **Display**: Good Display/Waveshare GDEH029A1-class panel
- **Controller**: UC8151
- **Size**: 2.9" (128×296 pixels)
- **Partial Refresh**: 260-300ms (with correct LUT)
- **Full Refresh**: 1.5-2.0 seconds

## Current Status

- ✅ Function exists in library
- ✅ Function is not currently used
- ✅ Library origin identified (Waveshare)
- ✅ Potential documentation sources found
- ✅ Related libraries found with similar functions
- ❌ Function signature is unknown
- ❌ No direct documentation found for `epaperDriver.so`
- ❌ No source code found in repository

## Recommendation

Before attempting to use `displayPartial()`, it's recommended to:

1. **Check Waveshare GitHub Repository**:
   - Visit https://github.com/waveshare/e-Paper
   - Look for source code for GDEH029A1/2.9" display driver
   - Check for `displayPartial` function definition
   - Look for examples or documentation

2. **Check PyPI Package Source**:
   - The newer `waveshare-epaper` v1.3.0 package may have source code
   - Install and inspect: `pip show waveshare-epaper` then check package location
   - May contain Python bindings or C source

3. **Check UC8151 Datasheet**:
   - Register 0x44/0x45 are mentioned for partial refresh window coordinates
   - This suggests the controller DOES support x/y coordinates
   - The C library may expose this via `displayPartial()`

4. **Compare with Adafruit Library**:
   - Adafruit CircuitPython UC8151D has documented `displayPartial` function
   - May provide clues about expected signature
   - Documentation: https://docs.circuitpython.org/projects/uc8151d/en/latest/api.html

5. **If Documentation Not Found**:
   - Carefully reverse engineer the function signature
   - Test thoroughly on hardware before deploying
   - Consider that it may have the same limitation as `displayRegion()` (full-width only)

The safest approach is to assume it may not support partial-width refreshes until proven otherwise, but it's worth investigating given that:
- It exists and is unused
- The UC8151 controller supports windowed updates (registers 0x44/0x45)
- Other libraries (Adafruit) implement `displayPartial` with x/y coordinates
- A newer version of the library exists that may have better documentation

## Test Script Created

A test script has been created at `docs/epaper/test_displayPartial.py` that:
- Tests 5 common function signatures
- Creates a small test image (12x12 pixels)
- Attempts to call `displayPartial()` with each signature
- Reports which signatures don't crash
- **WARNING**: Run on Raspberry Pi with hardware connected
- **WARNING**: Incorrect calls may cause crashes or display issues

### Usage:
```bash
# On Raspberry Pi:
cd /opt/DGTCentaurMods
python3 docs/epaper/test_displayPartial.py
```

### Function Addresses Found:
- `display`: 0x000013a8
- `displayPartial`: 0x000017c0
- `displayRegion`: 0x0000190c

### Tested Signatures:
1. `displayPartial(x1, y1, x2, y2, image_data)`
2. `displayPartial(x, y, width, height, image_data)`
3. `displayPartial(image_data, x1, y1, x2, y2)`
4. `displayPartial(image_data, x, y, width, height)`
5. `displayPartial(x1, y1, x2, y2, width, height, image_data)`

## Test Results

### Initial Test (2025-01-XX)
- **Test 1**: `displayPartial(x1, y1, x2, y2, image_data)` → **Segmentation fault**
- **Status**: First signature tested is incorrect
- **Next**: Use safer test script to test remaining signatures

### Safer Test Script Created
A new test script `test_displayPartial_safe.py` has been created that:
- Runs each test in a separate subprocess
- Prevents segfaults from killing the main process
- Tests all 6 signatures automatically
- Provides a summary of results

**Usage**:
```bash
cd /opt/DGTCentaurMods/docs/epaper
python3 test_displayPartial_safe.py
```

## Next Steps Summary

1. ✅ **Documentation Search**: Completed - no direct documentation found
2. ⏳ **Test Function Signatures**: 
   - Initial test: Test 1 failed with segfault
   - Safer test script created: `test_displayPartial_safe.py`
   - **Action needed**: Run safer test script on hardware
3. ⏳ **Check Waveshare GitHub**: Manual check recommended (visit repository)
4. ⏳ **Check Adafruit Documentation**: Manual check recommended (visit docs)
5. ⏳ **Reverse Engineering**: Would require ARM disassembly tools on target platform

