#!/usr/bin/env python3
"""
POC test for epd2in9b_V3 driver compatibility.
Tests if the V3 driver works with the display hardware in monochrome mode.
"""

import sys
import os
import time
from pathlib import Path
from PIL import Image, ImageDraw

# Get script directory
SCRIPT_DIR = Path(__file__).resolve().parent

# Add script directory to path to import local epd2in9b_V3
sys.path.insert(0, str(SCRIPT_DIR))

# Import the local copy of epd2in9b_V3
import epd2in9b_V3

# Import our epdconfig (epd2in9b_V3 will use it via fallback)
from epaper.framework.waveshare import epdconfig


def test_v3_driver():
    """Test the epd2in9b_V3 driver."""
    print("Testing epd2in9b_V3 driver...")
    
    try:
        # Initialize display
        epd = epd2in9b_V3.EPD()
        print(f"Display size: {epd.width}x{epd.height}")
        
        # Initialize hardware
        print("Initializing display...")
        # Check busy pin state before init
        busy_value = epdconfig.digital_read(epd.busy_pin)
        print(f"  Busy pin (GPIO {epd.busy_pin}) initial state: {busy_value} ({'HIGH' if busy_value else 'LOW'})")
        print("  (This may take a few seconds, checking busy pin...)")
        try:
            result = epd.init()
            if result != 0:
                print(f"ERROR: init() returned {result}")
                return False
            print("Display initialized successfully")
        except Exception as e:
            print(f"ERROR: {e}")
            current_busy = epdconfig.digital_read(epd.busy_pin)
            print(f"  Current busy pin value: {current_busy} ({'HIGH' if current_busy else 'LOW'})")
            import traceback
            traceback.print_exc()
            return False
        
        # Clear display
        print("Clearing display...")
        epd.Clear()
        print("Display cleared")
        time.sleep(2)
        
        # Test horizontal orientation (following example pattern)
        print("Testing horizontal orientation display...")
        # Horizontal image: (height, width) = (296, 128)
        HBlackimage = Image.new('1', (epd.height, epd.width), 255)
        drawblack = ImageDraw.Draw(HBlackimage)
        drawblack.text((10, 0), 'V3 Horizontal Test', fill=0)
        drawblack.text((10, 20), '2.9inch e-Paper b V3', fill=0)
        drawblack.line((20, 50, 70, 100), fill=0)
        drawblack.line((70, 50, 20, 100), fill=0)
        drawblack.rectangle((20, 50, 70, 100), outline=0)
        
        blackbuf = epd.getbuffer(HBlackimage)
        epd.display(blackbuf, None)  # Only black image, no red/yellow
        print("Horizontal display complete")
        time.sleep(3)
        
        # Test vertical orientation (following example pattern)
        print("Testing vertical orientation display...")
        # Vertical image: (width, height) = (128, 296)
        LBlackimage = Image.new('1', (epd.width, epd.height), 255)
        drawblack2 = ImageDraw.Draw(LBlackimage)
        drawblack2.text((2, 0), 'V3 Vertical Test', fill=0)
        drawblack2.text((2, 20), '2.9inch epd b V3', fill=0)
        drawblack2.line((10, 90, 60, 140), fill=0)
        drawblack2.line((60, 90, 10, 140), fill=0)
        drawblack2.rectangle((10, 90, 60, 140), outline=0)
        drawblack2.rectangle((70, 90, 120, 140), fill=0)
        
        blackbuf2 = epd.getbuffer(LBlackimage)
        epd.display(blackbuf2, None)
        print("Vertical display complete")
        time.sleep(3)
        
        # Test drawing shapes (following example pattern)
        print("Testing shape drawing...")
        HBlackimage2 = Image.new('1', (epd.height, epd.width), 255)
        drawblack3 = ImageDraw.Draw(HBlackimage2)
        drawblack3.text((10, 0), 'Shape Test', fill=0)
        drawblack3.rectangle((20, 50, 70, 100), outline=0)
        drawblack3.ellipse((80, 50, 130, 100), outline=0)
        drawblack3.polygon([(140, 50), (160, 100), (120, 100)], outline=0)
        
        blackbuf3 = epd.getbuffer(HBlackimage2)
        epd.display(blackbuf3, None)
        print("Shape drawing complete")
        time.sleep(3)
        
        # Final clear
        print("Clearing display...")
        epd.init()
        epd.Clear()
        time.sleep(2)
        
        # Sleep
        print("Putting display to sleep...")
        epd.sleep()
        print("Test complete - SUCCESS")
        return True
        
    except Exception as e:
        print(f"ERROR during test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_v3_driver()
    sys.exit(0 if success else 1)

