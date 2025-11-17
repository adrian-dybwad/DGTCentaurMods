# displayPartial() Investigation - Next Steps

## Completed Steps

### ✅ Step 1: Documentation Search
- **Status**: Completed
- **Findings**:
  - No direct documentation found for `epaperDriver.so`
  - Library origin identified: Waveshare (Good Display GDEH029A1, UC8151 controller)
  - Potential sources identified:
    - Waveshare GitHub: https://github.com/waveshare/e-Paper
    - Waveshare Wiki: https://www.waveshare.com/wiki/
    - PyPI package: `waveshare-epaper` v1.3.0 (newer version available)
    - Adafruit CircuitPython UC8151D library (has documented `displayPartial`)
  - UC8151 controller supports windowed updates (registers 0x44/0x45)

### ✅ Step 2: Function Analysis
- **Status**: Completed
- **Findings**:
  - Function exists: `displayPartial` at address 0x000017c0
  - Function is not currently used in codebase
  - Related functions found: `display`, `displayRegion`, `unsetRegion`
  - Library is ARM-based (for Raspberry Pi)

### ✅ Step 3: Test Script Creation
- **Status**: Completed
- **Created**: `docs/epaper/test_displayPartial.py`
- **Purpose**: Tests 5 common function signatures to determine correct one
- **Location**: Ready to run on Raspberry Pi hardware

## Next Steps (In Order)

### 1. Run Test Script on Hardware ⏳
**Priority**: High  
**Location**: Raspberry Pi with display connected  
**Script**: `docs/epaper/test_displayPartial.py`

**What it does**:
- Tests 5 common function signatures
- Creates a small test image (12x12 pixels)
- Attempts each signature and reports results
- **WARNING**: May cause crashes or display issues

**How to run**:
```bash
cd /opt/DGTCentaurMods
python3 docs/epaper/test_displayPartial.py
```

**Expected outcomes**:
- ✅ One signature works → We found the correct one!
- ❌ All signatures crash → May need different approach
- ⚠️ No visual change → May have same limitation as `displayRegion()`

### 2. Manual Documentation Checks ⏳
**Priority**: Medium  
**Action**: Manual review of external sources

**Waveshare GitHub Repository**:
- Visit: https://github.com/waveshare/e-Paper
- Look for: `RaspberryPi/c/examples/epd2in9d/` or similar
- Search for: `displayPartial` function definition
- Check: Function signature and usage examples

**Adafruit CircuitPython Documentation**:
- Visit: https://docs.circuitpython.org/projects/uc8151d/en/latest/api.html
- Look for: `displayPartial` function documentation
- Note: Function signature and parameter descriptions
- Use as: Reference for expected signature pattern

**PyPI Package Inspection**:
- Install: `pip install waveshare-epaper==1.3.0`
- Inspect: Package source code location
- Look for: C source files or Python bindings
- Check: Function definitions and documentation

### 3. Reverse Engineering (If Needed) ⏳
**Priority**: Low (only if test script doesn't work)  
**Requirements**: ARM disassembly tools on Raspberry Pi

**Tools needed**:
- `objdump` (usually available on Raspberry Pi)
- `gdb` (for debugging if needed)

**Commands**:
```bash
# On Raspberry Pi:
objdump -d /opt/DGTCentaurMods/epaper/epaperDriver.so | grep -A 50 displayPartial
```

**What to look for**:
- Function prologue (parameter setup)
- Register usage (r0-r3 for first 4 parameters on ARM)
- Stack usage (for additional parameters)
- Compare with `displayRegion()` implementation

### 4. UC8151 Datasheet Review ⏳
**Priority**: Medium  
**Purpose**: Understand controller capabilities

**Key registers to check**:
- Register 0x44/0x45: Partial refresh window coordinates
- Register 0x22: LUT for partial refresh
- Other window-related registers

**What to verify**:
- Does controller support partial-width refreshes?
- What are the coordinate formats?
- Are there alignment requirements?

### 5. Implementation (If Signature Found) ⏳
**Priority**: High (after signature confirmed)  
**Files to modify**:

1. **`epaper/driver.py`**:
   - Add new `partial_refresh_with_coords()` method
   - Use `displayPartial()` instead of `displayRegion()`
   - Update function signature to accept Region

2. **`epaper/regions.py`**:
   - Modify `expand_to_controller_alignment()` to only expand vertically
   - Keep original x coordinates

3. **`epaper/refresh_scheduler.py`**:
   - Update to use new driver method
   - Pass full Region instead of just y0, y1

4. **Testing**:
   - Test with small moving widget (ball)
   - Verify only necessary area refreshes
   - Check for ghosting or artifacts

## Risk Assessment

### Low Risk
- ✅ Documentation search (completed)
- ✅ Function analysis (completed)
- ✅ Test script creation (completed)

### Medium Risk
- ⚠️ Running test script (may crash, but won't damage hardware)
- ⚠️ Manual documentation checks (time-consuming but safe)

### High Risk
- ⚠️ Reverse engineering (complex, requires expertise)
- ⚠️ Implementation without proper testing (could break display updates)

## Success Criteria

**Function signature determined when**:
- Test script successfully calls `displayPartial()` without crash
- Display shows partial update in correct location
- Update is only the specified region (not full-width rows)

**Implementation successful when**:
- Small widgets (like ball) only refresh their area
- No full-width row refreshes for small changes
- Performance is equal or better than current implementation
- No ghosting or display artifacts

## Resources

- **Investigation Document**: `docs/epaper/displayPartial_investigation.md`
- **Test Script**: `docs/epaper/test_displayPartial.py`
- **Framework Guide**: `docs/epaper/framework_implementation_guide.md`
- **Waveshare GitHub**: https://github.com/waveshare/e-Paper
- **Adafruit Docs**: https://docs.circuitpython.org/projects/uc8151d/en/latest/api.html

## Notes

- The function exists and is unused, suggesting it may have been intended for this purpose
- UC8151 controller supports windowed updates, so hardware capability exists
- Other libraries implement similar functions with x/y coordinates
- Current limitation (full-width rows) is an API limitation, not hardware limitation

