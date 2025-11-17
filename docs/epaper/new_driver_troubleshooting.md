# New Driver Troubleshooting

**Date**: 2025-11-16  
**Status**: In Progress - Display works with old driver but not with new driver

## Problem Summary

The new pure Python Waveshare-style driver (`epaper/driver.py`) does not produce any visible output on the display, even though:
- The old `epaperDriver.so` works correctly
- The display hardware is functional
- Commands appear to be sent (timing is correct: 1.8s for full refresh)
- No errors are reported

## What We've Tried

### 1. GPIO Pin Configurations
- ✅ RST=17, DC=25, CS=8, BUSY=24 (standard Waveshare)
- ✅ RST=17, DC=25, CS=7, BUSY=24 (CE1)
- ✅ RST=17, DC=25, CS=0, BUSY=24
- ✅ RST=17, DC=25, CS=1, BUSY=24
- ✅ Various other pin combinations
- ❌ None produced visible output

### 2. SPI Device Configurations
- ✅ SPI bus 0, device 0
- ✅ SPI bus 0, device 1
- ✅ SPI bus 1, device 0
- ✅ SPI bus 1, device 1
- ❌ None produced visible output

### 3. CS Pin Handling
- ✅ Hardware CS (EPAPER_USE_HW_CS=true)
- ✅ Manual CS control (EPAPER_USE_HW_CS=false)
- ❌ Neither produced visible output

### 4. Image Conversion Formulas
- ✅ New formula: `y * bytes_per_row + (x // 8)`
- ✅ Old formula: `int((x + y * width) / 8)`
- ❌ Neither produced visible output

### 5. BUSY Pin Handling
- ✅ Skipping BUSY wait (EPAPER_SKIP_BUSY=true)
- ✅ Inverted BUSY logic (EPAPER_BUSY_INVERTED=true)
- ✅ Standard BUSY logic
- ❌ None produced visible output

### 6. SPI Settings (Next to Test)
- ⏳ SPI Mode 0, 1, 2, 3
- ⏳ SPI Speed: 1MHz, 2MHz, 4MHz, 8MHz

## Observations

1. **Timing is correct**: Full refresh takes 1.8s (correct for UC8151)
2. **Commands are sent**: Logs show all commands being sent
3. **No errors**: No exceptions or SPI errors
4. **Display doesn't respond**: No visible change on display

## Possible Issues

### 1. Initialization Sequence
The old driver might use a different initialization sequence. The UC8151 datasheet shows several possible initialization sequences depending on the panel configuration.

**Current sequence**:
1. Reset (RST LOW → HIGH)
2. PSR (Panel Setting) - 0xBF, 0x0D
3. PWR (Power Setting) - 0x03, 0x00, 0x2B, 0x2B, 0x09
4. BTST (Booster Soft Start) - 0x17, 0x17, 0x17
5. PLL - 0x3C
6. TSE (Temperature Sensor) - 0x00
7. TRES (Resolution) - 128x296
8. CDI (VCOM and Data Interval) - 0x97
9. PON (Power On)

**Possible issues**:
- Missing commands?
- Wrong command parameters?
- Wrong command order?
- Missing delays between commands?

### 2. SPI Communication
The old driver might use different SPI settings or communication method.

**Possible issues**:
- Wrong SPI mode (currently using mode 0)
- Wrong SPI speed (currently using 4MHz)
- Different CS handling
- Different data format

### 3. Command/Data Format
The old driver might send commands or data in a different format.

**Possible issues**:
- Different byte order?
- Different bit order?
- Additional padding bytes?
- Different command encoding?

### 4. Hardware Differences
The actual hardware might be different from what we assume.

**Possible issues**:
- Different display model (not GDEH029A1)?
- Different controller (not UC8151)?
- Custom initialization required?

## Next Steps

1. **Test SPI settings**: Run `test_spi_settings.py` to try different SPI modes and speeds
2. **Compare initialization**: Try to capture what the old driver actually does (strace, logic analyzer)
3. **Check hardware docs**: Look for actual hardware schematics or documentation
4. **Try different init sequence**: Experiment with different UC8151 initialization sequences
5. **Verify command format**: Check if commands need to be sent differently

## Test Scripts Created

- `epaper/test_driver.py` - Basic driver test
- `epaper/test_spi_devices.py` - Test different SPI devices
- `epaper/test_gpio_pins.py` - Test GPIO pin toggling
- `epaper/test_old_driver_simple.py` - Test old driver
- `epaper/test_new_driver_configs.py` - Test pin/SPI combinations
- `epaper/test_spi_settings.py` - Test SPI mode/speed combinations

## Environment Variables

All configuration is via environment variables:
- `EPAPER_RST_PIN` - Reset pin (default: 17)
- `EPAPER_DC_PIN` - Data/Command pin (default: 25)
- `EPAPER_CS_PIN` - Chip Select pin (default: 8)
- `EPAPER_BUSY_PIN` - Busy pin (default: 24)
- `EPAPER_SPI_BUS` - SPI bus (default: 0)
- `EPAPER_SPI_DEVICE` - SPI device (default: 0)
- `EPAPER_SPI_MODE` - SPI mode (default: 0)
- `EPAPER_SPI_SPEED` - SPI speed in Hz (default: 4000000)
- `EPAPER_USE_HW_CS` - Use hardware CS (default: false)
- `EPAPER_SKIP_BUSY` - Skip BUSY pin wait (default: false)
- `EPAPER_BUSY_INVERTED` - Invert BUSY pin logic (default: false)
- `EPAPER_USE_OLD_FORMULA` - Use old image conversion formula (default: false)

