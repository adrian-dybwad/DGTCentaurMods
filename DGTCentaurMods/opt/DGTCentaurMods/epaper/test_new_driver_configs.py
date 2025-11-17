#!/usr/bin/env python3
"""
Test different configurations for the new driver to match old driver behavior.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

import logging
import time
from PIL import Image

# Reduce logging noise
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from epaper.driver import Driver

def test_config(rst, dc, cs, busy, spi_bus, spi_device, use_hw_cs, use_old_formula, description):
    """Test a specific configuration."""
    print(f"\n{'='*60}")
    print(f"Testing: {description}")
    print(f"  RST={rst}, DC={dc}, CS={cs}, BUSY={busy}")
    print(f"  SPI: bus={spi_bus}, device={spi_device}, HW_CS={use_hw_cs}")
    print(f"  Old formula: {use_old_formula}")
    print(f"{'='*60}")
    
    try:
        # Set environment variables
        os.environ['EPAPER_RST_PIN'] = str(rst)
        os.environ['EPAPER_DC_PIN'] = str(dc)
        os.environ['EPAPER_CS_PIN'] = str(cs)
        os.environ['EPAPER_BUSY_PIN'] = str(busy)
        os.environ['EPAPER_SPI_BUS'] = str(spi_bus)
        os.environ['EPAPER_SPI_DEVICE'] = str(spi_device)
        os.environ['EPAPER_SKIP_BUSY'] = 'true'
        if use_hw_cs:
            os.environ['EPAPER_USE_HW_CS'] = 'true'
        else:
            os.environ.pop('EPAPER_USE_HW_CS', None)
        if use_old_formula:
            os.environ['EPAPER_USE_OLD_FORMULA'] = 'true'
        else:
            os.environ.pop('EPAPER_USE_OLD_FORMULA', None)
        
        # Reload driver module to pick up new config
        import importlib
        import epaper.driver
        importlib.reload(epaper.driver)
        Driver = epaper.driver.Driver
        
        driver = Driver()
        driver.init()
        
        # Create test image: black screen
        test_image = Image.new("1", (driver.width, driver.height), 0)  # Black
        
        print("Performing full refresh with BLACK screen...")
        start = time.time()
        driver.full_refresh(test_image)
        elapsed = time.time() - start
        
        if elapsed < 1.0:
            print(f"  ⚠️  Refresh too fast ({elapsed:.2f}s) - likely not working")
            driver.shutdown()
            return False
        
        print(f"  ✓ Refresh took {elapsed:.2f}s (correct timing)")
        print(f"  Check the display - do you see a BLACK screen?")
        print(f"  Type 'yes' if you see black, or press Enter to continue...")
        response = input().strip().lower()
        
        if response == 'yes':
            print(f"\n🎉 SUCCESS! Working configuration found!")
            print(f"  RST={rst}, DC={dc}, CS={cs}, BUSY={busy}")
            print(f"  SPI: bus={spi_bus}, device={spi_device}, HW_CS={use_hw_cs}")
            print(f"  Old formula: {use_old_formula}")
            print(f"\n  Use these environment variables:")
            print(f"    export EPAPER_RST_PIN={rst}")
            print(f"    export EPAPER_DC_PIN={dc}")
            print(f"    export EPAPER_CS_PIN={cs}")
            print(f"    export EPAPER_BUSY_PIN={busy}")
            print(f"    export EPAPER_SPI_BUS={spi_bus}")
            print(f"    export EPAPER_SPI_DEVICE={spi_device}")
            if use_hw_cs:
                print(f"    export EPAPER_USE_HW_CS=true")
            else:
                print(f"    unset EPAPER_USE_HW_CS")
            if use_old_formula:
                print(f"    export EPAPER_USE_OLD_FORMULA=true")
            else:
                print(f"    unset EPAPER_USE_OLD_FORMULA")
            print(f"    export EPAPER_SKIP_BUSY=true")
            
            driver.shutdown()
            return True
        else:
            print(f"  ✗ No black screen visible")
            driver.shutdown()
            return False
            
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing different configurations for the new driver")
    print("You should see a BLACK screen when the correct configuration is found")
    print()
    
    # Configurations to try (most likely first)
    configs = [
        # Standard Waveshare 2.9" with hardware CS
        (17, 25, 8, 24, 0, 0, True, False, "Standard Waveshare (RST=17, DC=25, CS=8, BUSY=24, HW_CS, new formula)"),
        (17, 25, 8, 24, 0, 0, True, True, "Standard Waveshare (RST=17, DC=25, CS=8, BUSY=24, HW_CS, old formula)"),
        
        # Without hardware CS
        (17, 25, 8, 24, 0, 0, False, False, "Standard Waveshare (RST=17, DC=25, CS=8, BUSY=24, manual CS, new formula)"),
        (17, 25, 8, 24, 0, 0, False, True, "Standard Waveshare (RST=17, DC=25, CS=8, BUSY=24, manual CS, old formula)"),
        
        # CE1 instead of CE0
        (17, 25, 7, 24, 0, 1, True, False, "Waveshare CE1 (RST=17, DC=25, CS=7, BUSY=24, HW_CS, new formula)"),
        (17, 25, 7, 24, 0, 1, True, True, "Waveshare CE1 (RST=17, DC=25, CS=7, BUSY=24, HW_CS, old formula)"),
        
        # Different SPI device
        (17, 25, 8, 24, 0, 1, True, False, "SPI device 1 (RST=17, DC=25, CS=8, BUSY=24, HW_CS, new formula)"),
        (17, 25, 8, 24, 0, 1, True, True, "SPI device 1 (RST=17, DC=25, CS=8, BUSY=24, HW_CS, old formula)"),
    ]
    
    for rst, dc, cs, busy, spi_bus, spi_device, use_hw_cs, use_old_formula, desc in configs:
        if test_config(rst, dc, cs, busy, spi_bus, spi_device, use_hw_cs, use_old_formula, desc):
            print("\n✅ Found working configuration!")
            break
    else:
        print("\n❌ None of the tested configurations worked")
        print("The display may use different pins or need a different initialization sequence")

