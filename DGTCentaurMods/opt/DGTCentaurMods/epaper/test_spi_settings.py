#!/usr/bin/env python3
"""
Test different SPI settings (mode, speed) to find what works.
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

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from epaper.driver import Driver

def test_spi_settings(spi_mode, spi_speed, description):
    """Test specific SPI mode and speed."""
    print(f"\n{'='*60}")
    print(f"Testing: {description}")
    print(f"  SPI Mode: {spi_mode}, Speed: {spi_speed}Hz")
    print(f"{'='*60}")
    
    try:
        # Set environment variables
        os.environ['EPAPER_RST_PIN'] = '17'
        os.environ['EPAPER_DC_PIN'] = '25'
        os.environ['EPAPER_CS_PIN'] = '8'
        os.environ['EPAPER_BUSY_PIN'] = '24'
        os.environ['EPAPER_SPI_BUS'] = '0'
        os.environ['EPAPER_SPI_DEVICE'] = '0'
        os.environ['EPAPER_SPI_MODE'] = str(spi_mode)
        os.environ['EPAPER_SPI_SPEED'] = str(spi_speed)
        os.environ['EPAPER_USE_HW_CS'] = 'true'
        os.environ['EPAPER_SKIP_BUSY'] = 'true'
        os.environ['EPAPER_USE_OLD_FORMULA'] = 'true'  # Try old formula
        
        # Reload driver module
        import importlib
        import epaper.driver
        importlib.reload(epaper.driver)
        Driver = epaper.driver.Driver
        
        driver = Driver()
        driver.init()
        
        # Create black image
        test_image = Image.new("1", (driver.width, driver.height), 0)
        
        print("Performing full refresh with BLACK screen...")
        start = time.time()
        driver.full_refresh(test_image)
        elapsed = time.time() - start
        
        if elapsed < 1.0:
            print(f"  ⚠️  Refresh too fast ({elapsed:.2f}s)")
            driver.shutdown()
            return False
        
        print(f"  ✓ Refresh took {elapsed:.2f}s")
        print(f"  Check the display - do you see a BLACK screen?")
        print(f"  Type 'yes' if you see black, or press Enter to continue...")
        response = input().strip().lower()
        
        driver.shutdown()
        
        if response == 'yes':
            print(f"\n🎉 SUCCESS! Working SPI settings:")
            print(f"  Mode: {spi_mode}, Speed: {spi_speed}Hz")
            return True
        else:
            print(f"  ✗ No black screen visible")
            return False
            
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        return False

if __name__ == "__main__":
    print("Testing different SPI settings")
    print("Common SPI modes: 0, 1, 2, 3")
    print("Common speeds: 1000000 (1MHz), 2000000 (2MHz), 4000000 (4MHz), 8000000 (8MHz)")
    print()
    
    # Test different SPI modes and speeds
    configs = [
        (0, 4000000, "Mode 0, 4MHz (default)"),
        (0, 2000000, "Mode 0, 2MHz"),
        (0, 1000000, "Mode 0, 1MHz"),
        (0, 8000000, "Mode 0, 8MHz"),
        (1, 4000000, "Mode 1, 4MHz"),
        (2, 4000000, "Mode 2, 4MHz"),
        (3, 4000000, "Mode 3, 4MHz"),
    ]
    
    for spi_mode, spi_speed, desc in configs:
        if test_spi_settings(spi_mode, spi_speed, desc):
            print("\n✅ Found working SPI settings!")
            break
    else:
        print("\n❌ None of the SPI settings worked")
        print("The issue may be with the initialization sequence or command format")

