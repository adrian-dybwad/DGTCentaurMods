# Color Inversion Root Cause Analysis

## Problem Statement
Colors are inverted on display: black pixels appear white, white pixels appear black.

## Analysis from 5 Perspectives

### Agent 1: Waveshare Reference Implementation Analysis
**Finding**: Original `epd2in9d.py` DisplayPartial (lines 255-280):
- 0x10 sends: `image` (original buffer)
- 0x13 sends: `~image` (inverted buffer)
- Buffer format: 0 bit = black, 1 bit = white (standard PIL conversion)

**Conclusion**: Our implementation matches the reference exactly.

### Agent 2: Similar Display Models Analysis
**Finding**: `epd2in13d.py` (similar 2.13" display):
- Uses identical pattern: 0x10 = original, 0x13 = inverted
- Same buffer format as epd2in9d

**Finding**: `epd7in5b_V2.py` (line 200-205):
- **CRITICAL**: Explicitly inverts buffer in `getbuffer()`:
  ```python
  # "The bytes need to be inverted, because in the PIL world 0=black and 1=white, 
  # but in the e-paper world 0=white and 1=black."
  for i in range(len(buf)):
      buf[i] ^= 0xFF
  ```
- Then inverts back in `display()` before sending

**Conclusion**: Some Waveshare displays require inverted buffer format.

### Agent 3: Original Native Driver Analysis
**Finding**: `display/epaper_service/drivers/native.py` (line 32-41):
- Uses same buffer format as current code: 0 bit = black, 1 bit = white
- Starts with 0xFF (all white)
- This driver works correctly with DGT Centaur hardware

**Conclusion**: Original driver uses non-inverted format and works.

### Agent 4: DisplayPartial Command Analysis
**Finding**: UC8151 controller commands:
- 0x10: Write old state (for comparison)
- 0x13: Write new state
- DisplayPartial sends both to enable fast partial updates

**Finding**: The inversion in DisplayPartial (`buf = ~image`) is for the OLD state (0x10), not the new state.

**Conclusion**: The pattern is correct, but buffer format may be wrong.

### Agent 5: Hardware-Specific Requirements
**Finding**: DGT Centaur uses UC8151 controller with 2.9" display
- Original driver works with non-inverted format
- Waveshare driver may expect different format
- Hardware may interpret buffer bits differently

**Conclusion**: Need to test if hardware expects inverted format despite original driver.

## Root Cause Hypothesis

**PRIMARY HYPOTHESIS**: The Waveshare `DisplayPartial` implementation expects the buffer in a different format than what `getbuffer()` produces, OR the hardware interprets the buffer differently when using Waveshare commands vs. original driver commands.

**EVIDENCE**:
1. Original driver works with non-inverted format
2. Some Waveshare displays (epd7in5b_V2) require inverted format
3. Our current code matches reference epd2in9d exactly
4. Colors are inverted, suggesting format mismatch

## Proposed Solutions (in order of likelihood)

### Solution 1: Invert Buffer in getbuffer() (HIGHEST PROBABILITY)
**Action**: Modify `getbuffer()` to invert the buffer format:
- Change: Start with 0x00 (all black), set bits to 1 for black pixels
- OR: Keep current logic but XOR entire buffer with 0xFF at end
- **Rationale**: Matches epd7in5b_V2 pattern, hardware may expect inverted format

### Solution 2: Invert in DisplayPartial Only
**Action**: Keep `getbuffer()` as-is, but invert buffer before calling `DisplayPartial`
- **Rationale**: DisplayPartial may expect different format than full display

### Solution 3: Check Hardware Configuration
**Action**: Verify if panel setting command (0x00) needs different value
- **Rationale**: Some displays have configurable pixel polarity

### Solution 4: Invert Both 0x10 and 0x13 Data
**Action**: Modify DisplayPartial to send inverted data for both commands
- **Rationale**: Hardware may interpret both commands inverted

## Recommended Fix

**Try Solution 1 first**: Invert the buffer in `getbuffer()` by XORing with 0xFF after conversion, similar to epd7in5b_V2. This is the most common pattern for displays that require inverted format.

