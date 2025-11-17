#!/usr/bin/env python3
"""
Test different SPI devices to find which one the display uses.
"""

import sys
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

import logging
import time
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from epaper.driver import Driver

def test_spi_device(spi_bus, spi_device):
    """Test a specific SPI device."""
    print(f"\n{'='*60}")
    print(f"Testing SPI bus {spi_bus}, device {spi_device}")
    print(f"{'='*60}")
    
    try:
        import os
        os.environ['EPAPER_SPI_BUS'] = str(spi_bus)
        os.environ['EPAPER_SPI_DEVICE'] = str(spi_device)
        os.environ['EPAPER_SKIP_BUSY'] = 'true'
        os.environ['EPAPER_USE_HW_CS'] = 'true'
        
        driver = Driver()
        driver.init()
        
        # Create a test pattern: checkerboard
        test_image = Image.new("1", (driver.width, driver.height), 255)  # White
        from PIL import ImageDraw
        draw = ImageDraw.Draw(test_image)
        
        # Draw a checkerboard pattern
        square_size = 20
        for y in range(0, driver.height, square_size * 2):
            for x in range(0, driver.width, square_size * 2):
                draw.rectangle((x, y, x + square_size - 1, y + square_size - 1), fill=0)  # Black
        for y in range(square_size, driver.height, square_size * 2):
            for x in range(square_size, driver.width, square_size * 2):
                draw.rectangle((x, y, x + square_size - 1, y + square_size - 1), fill=0)  # Black
        
        print(f"Performing full refresh with checkerboard pattern...")
        driver.full_refresh(test_image)
        print(f"Refresh complete. Check the display - do you see a checkerboard pattern?")
        print(f"Press Enter to continue to next test, or Ctrl+C to stop...")
        input()
        
        driver.shutdown()
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing different SPI devices to find which one the display uses.")
    print("You should see a checkerboard pattern on the display when the correct device is found.")
    print()
    
    # Test common SPI device combinations
    devices_to_test = [
        (0, 0),  # SPI0, CE0 (default)
        (0, 1),  # SPI0, CE1
        (1, 0),  # SPI1, CE0
        (1, 1),  # SPI1, CE1
    ]
    
    for spi_bus, spi_device in devices_to_test:
        if test_spi_device(spi_bus, spi_device):
            print(f"\n✓ SPI bus {spi_bus}, device {spi_device} works!")
            print(f"Use: export EPAPER_SPI_BUS={spi_bus} EPAPER_SPI_DEVICE={spi_device}")
        else:
            print(f"\n✗ SPI bus {spi_bus}, device {spi_device} failed")
    
    print("\nDone testing all SPI devices.")

