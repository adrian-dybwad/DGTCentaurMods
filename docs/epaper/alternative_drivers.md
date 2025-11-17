# Alternative ePaper Driver Libraries

## Overview

Since `epaperDriver.so` lacks documentation for `displayPartial()`, here are well-documented alternative drivers that support UC8151/GDEH029A1 displays. These libraries have full source code available and can be used as replacements or references.

## Top Recommendations

### 🥇 1. Waveshare e-Paper Python Library (BEST OPTION)
**Source**: https://github.com/waveshare/e-Paper  
**Language**: Python  
**Status**: ✅ Official Waveshare library with full source code  
**License**: Check repository for license terms

**Why This Is Best**:
- Pure Python (no compiled .so needed)
- Full source code available
- Official Waveshare library (same vendor as your hardware)
- Supports GDEH029A1/2.9" displays
- Well-documented with examples
- Can see exactly how partial refreshes work

**Installation**:
```bash
git clone https://github.com/waveshare/e-Paper.git
cd e-Paper/RaspberryPi/python/lib
```

**Key File**: `epd2in9d.py` - Driver for 2.9" display (GDEH029A1)

**To Check for displayPartial**:
```bash
cd e-Paper/RaspberryPi/python/lib
grep -i "partial\|displayPart" epd2in9d.py
cat epd2in9d.py | grep -A 10 "def.*partial"
```

**Integration**:
- Complete replacement for `epaperDriver.so`
- Pure Python implementation - easier to debug and modify
- Adapt to your framework's driver interface

### 🥈 2. Adafruit CircuitPython UC8151D Library
**Source**: https://github.com/adafruit/Adafruit_CircuitPython_UC8151D  
**Documentation**: https://docs.circuitpython.org/projects/uc8151d/en/latest/api.html  
**Language**: Python (CircuitPython, but can be adapted)  
**Status**: ✅ Well-documented, full source code

**Why This Is Good**:
- Has documented `displayPartial()` function
- Full source code available
- Excellent documentation
- Can be adapted for standard Python (remove CircuitPython dependencies)

**Key Function** (from documentation):
```python
def displayPartial(self, image, x, y):
    """Display a partial update at the given x, y coordinates"""
```

**Installation**:
```bash
git clone https://github.com/adafruit/Adafruit_CircuitPython_UC8151D.git
cd Adafruit_CircuitPython_UC8151D
```

**To Check Implementation**:
```bash
grep -A 20 "def displayPartial" adafruit_uc8151d.py
```

### 🥉 3. PyPI waveshare-epaper Package (v1.3.0)
**Package**: `waveshare-epaper` v1.3.0  
**Source**: https://pypi.org/project/waveshare-epaper/  
**Language**: Python  
**Status**: ✅ Newer than current driver (July 2024)

**Why This Is Useful**:
- Newer version than current `epaperDriver.so` (July 2024 vs Sep 2023)
- May have better documentation
- Source code should be available via PyPI

**Installation**:
```bash
pip install waveshare-epaper==1.3.0
# Find source location:
pip show -f waveshare-epaper
# Or download source:
pip download --no-binary :all: waveshare-epaper==1.3.0
```

## Other Python Libraries

### 4. MicroPython 2.9-inch ePaper Library
**Source**: https://github.com/rdagger/MicroPython-2.9-inch-ePaper-Library  
**Language**: MicroPython/Python  
**Status**: Community library

**Features**:
- Pure Python implementation
- Source code available
- Supports 2.9" ePaper displays
- Documented with examples

**Note**: May need adaptation for standard Python (not MicroPython)

## C/C++ Libraries (For Reference)

### 4. GxEPD2 Library
**Source**: https://github.com/ZinggJM/GxEPD2  
**Language**: C++ (Arduino)  
**Status**: Well-documented, widely used

**Features**:
- Supports partial refreshes with x/y coordinates
- `setPartialWindow(x, y, width, height)` function
- Excellent documentation
- Can be used as reference for understanding partial refresh implementation

**Note**: Arduino/C++ library, but can be used as reference for Python implementation

### 5. Adafruit EPD Library
**Source**: https://github.com/adafruit/Adafruit_EPD  
**Language**: C++ (Arduino)  
**Status**: Well-documented

**Features**:
- Supports various ePaper displays
- Good documentation
- Can be used as reference

## CircuitPython Libraries (For Reference)

### 6. Adafruit CircuitPython UC8151D
**Source**: https://github.com/adafruit/Adafruit_CircuitPython_UC8151D  
**Documentation**: https://docs.circuitpython.org/projects/uc8151d/en/latest/api.html  
**Language**: Python (CircuitPython)

**Features**:
- Has documented `displayPartial()` function
- Full source code available
- Can be adapted for standard Python
- Excellent documentation

**Key Function**:
```python
def displayPartial(self, image, x, y):
    """Display a partial update"""
```

## Quick Start Guide

### Step 1: Clone Waveshare Repository (Recommended)
```bash
git clone https://github.com/waveshare/e-Paper.git
cd e-Paper/RaspberryPi/python/lib
```

### Step 2: Examine the Driver
```bash
# Look for partial refresh functions
grep -i "partial\|displayPart" epd2in9d.py

# View the full driver
cat epd2in9d.py

# Check function signatures
grep -A 10 "def.*partial\|def.*displayPart" epd2in9d.py
```

### Step 3: Compare with Current Implementation
- See how Waveshare implements partial refreshes
- Note the function signature and parameters
- Understand the image format requirements
- Check if they use x/y coordinates

### Step 4: Integration Strategy

**Complete Replacement Approach**:
- Replace `epaperDriver.so` entirely with Waveshare Python library
- Use `epd2in9d.py` as the base driver
- Adapt to your framework's driver interface
- Pure Python - easier to debug, modify, and understand
- No more undocumented compiled library

## Comparison Table

| Library | Language | Source Code | Documentation | Partial Refresh | Recommendation |
|---------|----------|-------------|---------------|-----------------|----------------|
| **Waveshare e-Paper** | Python | ✅ Yes | ✅ Good | ✅ Yes | ⭐⭐⭐⭐⭐ Best |
| **Adafruit UC8151D** | Python (CircuitPython) | ✅ Yes | ✅ Excellent | ✅ Yes | ⭐⭐⭐⭐ Very Good |
| **PyPI waveshare-epaper** | Python | ✅ Yes | ⚠️ Unknown | ❓ Unknown | ⭐⭐⭐ Good |
| **MicroPython Library** | MicroPython | ✅ Yes | ✅ Good | ❓ Unknown | ⭐⭐⭐ Good |
| **GxEPD2** | C++ (Arduino) | ✅ Yes | ✅ Excellent | ✅ Yes | ⭐⭐⭐ Reference Only |
| **epaperDriver.so** | C (compiled) | ❌ No | ❌ None | ❓ Unknown | ❌ Being Replaced |

## Implementation Examples

### Waveshare Python Library Usage (Expected)
```python
from epd2in9d import EPD

epd = EPD()
epd.init()

# Partial refresh (if available)
epd.displayPartial(image, x, y, width, height)
# or
epd.displayPart(image, x, y, width, height)
```

### Adafruit UC8151D Usage (Documented)
```python
from adafruit_uc8151d import UC8151D

display = UC8151D(...)
display.displayPartial(image, x, y)
```

## Action Plan

### Immediate Next Steps

1. **Clone Waveshare repository**:
   ```bash
   git clone https://github.com/waveshare/e-Paper.git
   cd e-Paper/RaspberryPi/python/lib
   ```

2. **Examine the driver**:
   ```bash
   # Look for partial refresh functions
   grep -i "partial\|displayPart" epd2in9d.py
   
   # View function signatures
   grep -A 20 "def.*partial\|def.*displayPart" epd2in9d.py
   
   # View full driver
   cat epd2in9d.py
   ```

3. **Understand the Waveshare implementation**:
   - Review how Waveshare implements partial refreshes
   - Note the function signature and parameters
   - See what image format they use (small vs full-width)
   - Understand coordinate system (top vs bottom origin)
   - Compare with what we learned from testing `epaperDriver.so` (to understand why it failed)

4. **Replace epaperDriver.so completely**:
   - Remove all references to `epaperDriver.so`
   - Use Waveshare Python library (`epd2in9d.py`) as the driver
   - Adapt the Waveshare driver to match your framework's `Driver` interface
   - Implement all methods: `init()`, `reset()`, `full_refresh()`, `partial_refresh()`, `sleep()`, `shutdown()`

5. **Update framework**:
   - Update `epaper/driver.py` to use Waveshare library instead of `.so`
   - Modify `epaper/regions.py` to only expand vertically (no full-width requirement)
   - Test with moving widgets (ball) to verify partial-width refreshes work correctly
   - Remove `epaperDriver.so` file from repository

## Resources

- **Waveshare GitHub**: https://github.com/waveshare/e-Paper
- **Waveshare Wiki**: https://www.waveshare.com/wiki/
- **Adafruit UC8151D**: https://github.com/adafruit/Adafruit_CircuitPython_UC8151D
- **GxEPD2 Library**: https://github.com/ZinggJM/GxEPD2
- **UC8151 Datasheet**: Search for "UC8151 datasheet" for register-level documentation

