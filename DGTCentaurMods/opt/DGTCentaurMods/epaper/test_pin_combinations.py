#!/usr/bin/env python3
"""
Test different GPIO pin combinations to find the correct configuration.
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
    level=logging.WARNING,  # Reduce noise
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from epaper.driver import Driver

# Common pin combinations to try
PIN_COMBINATIONS = [
    # (RST, DC, CS, BUSY) - typical Waveshare 2.9"
    (17, 25, 8, 24),
    (17, 25, 7, 24),  # CE1 instead of CE0
    (17, 25, 0, 24),  # GPIO 0
    (17, 25, 1, 24),  # GPIO 1
    # Alternative configurations
    (18, 25, 8, 24),
    (17, 24, 8, 25),  # Swapped DC and BUSY
    (22, 25, 8, 24),
    (27, 25, 8, 24),
]

def test_pin_combination(rst, dc, cs, busy, use_hw_cs=True):
    """Test a specific pin combination."""
    print(f"\n{'='*60}")
    print(f"Testing: RST={rst}, DC={dc}, CS={cs}, BUSY={busy}, HW_CS={use_hw_cs}")
    print(f"{'='*60}")
    
    try:
        # Set environment variables
        os.environ['EPAPER_RST_PIN'] = str(rst)
        os.environ['EPAPER_DC_PIN'] = str(dc)
        os.environ['EPAPER_CS_PIN'] = str(cs)
        os.environ['EPAPER_BUSY_PIN'] = str(busy)
        os.environ['EPAPER_SKIP_BUSY'] = 'true'
        if use_hw_cs:
            os.environ['EPAPER_USE_HW_CS'] = 'true'
        else:
            os.environ.pop('EPAPER_USE_HW_CS', None)
        
        # Reload the driver module to pick up new pin values
        import importlib
        import epaper.driver
        importlib.reload(epaper.driver)
        Driver = epaper.driver.Driver
        
        driver = Driver()
        driver.init()
        
        # Create a simple test pattern: alternating black and white stripes
        test_image = Image.new("1", (driver.width, driver.height), 255)  # White
        from PIL import ImageDraw
        draw = ImageDraw.Draw(test_image)
        
        # Draw vertical stripes
        stripe_width = 20
        for x in range(0, driver.width, stripe_width * 2):
            draw.rectangle((x, 0, x + stripe_width - 1, driver.height - 1), fill=0)  # Black
        
        print(f"Performing full refresh with stripe pattern...")
        start = time.time()
        driver.full_refresh(test_image)
        elapsed = time.time() - start
        
        if elapsed < 1.0:
            print(f"  ⚠️  Refresh too fast ({elapsed:.2f}s) - likely not working")
            driver.shutdown()
            return False
        
        print(f"  ✓ Refresh took {elapsed:.2f}s (correct timing)")
        print(f"  Check the display - do you see vertical black and white stripes?")
        print(f"  Type 'yes' if you see the pattern, or press Enter to continue...")
        response = input().strip().lower()
        
        driver.shutdown()
        
        if response == 'yes':
            print(f"\n🎉 SUCCESS! Correct pins: RST={rst}, DC={dc}, CS={cs}, BUSY={busy}, HW_CS={use_hw_cs}")
            return True
        else:
            print(f"  ✗ No pattern visible")
            return False
            
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
        return False

if __name__ == "__main__":
    print("Testing different GPIO pin combinations")
    print("You should see vertical black and white stripes when the correct pins are found")
    print()
    
    # First, verify old driver works
    print("STEP 1: Verify old driver works")
    print("Run: python3 epaper/test_old_driver.py")
    print("Press Enter after confirming old driver works...")
    input()
    
    # Test each combination
    for rst, dc, cs, busy in PIN_COMBINATIONS:
        # Try with hardware CS first
        if test_pin_combination(rst, dc, cs, busy, use_hw_cs=True):
            print("\n✅ Found working pin configuration!")
            break
        
        # Try without hardware CS
        if test_pin_combination(rst, dc, cs, busy, use_hw_cs=False):
            print("\n✅ Found working pin configuration!")
            break
    else:
        print("\n❌ None of the tested pin combinations worked")
        print("The display may use different pins, or there may be a hardware issue")

