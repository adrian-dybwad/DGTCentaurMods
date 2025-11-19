#!/usr/bin/env python3
"""
POC test for epd2in9_V2 driver compatibility.
Tests if the V2 driver works with the display hardware.
"""

import sys
import os
import time
from pathlib import Path
from PIL import Image, ImageDraw

# Get script directory
SCRIPT_DIR = Path(__file__).resolve().parent

# Add script directory to path to import local epd2in9_V2
sys.path.insert(0, str(SCRIPT_DIR))

# Import the local copy of epd2in9_V2
import epd2in9_V2

# Import our epdconfig (epd2in9_V2 will use it via fallback)
from epaper.framework.waveshare import epdconfig


def test_v2_driver():
    """Test the epd2in9_V2 driver."""
    print("Testing epd2in9_V2 driver...")
    
    try:
        # Initialize display
        epd = epd2in9_V2.EPD()
        print(f"Display size: {epd.width}x{epd.height}")
        
        # Initialize hardware
        print("Initializing display...")
        result = epd.init()
        if result != 0:
            print(f"ERROR: init() returned {result}")
            return False
        print("Display initialized successfully")
        
        # Clear display
        print("Clearing display...")
        epd.Clear()
        print("Display cleared")
        time.sleep(2)
        
        # Test full refresh
        print("Testing full refresh...")
        image = Image.new('1', (epd.width, epd.height), 255)  # White
        draw = ImageDraw.Draw(image)
        draw.rectangle([10, 10, 50, 50], fill=0)  # Black rectangle
        draw.text((10, 60), "V2 Full Test", fill=0)
        
        buf = epd.getbuffer(image)
        epd.display(buf)
        print("Full refresh complete")
        time.sleep(3)
        
        # Test partial refresh
        print("Testing partial refresh...")
        # Create new image with updated content
        image2 = Image.new('1', (epd.width, epd.height), 255)
        draw2 = ImageDraw.Draw(image2)
        draw2.rectangle([10, 10, 50, 50], fill=255)  # White rectangle (erase)
        draw2.rectangle([60, 10, 100, 50], fill=0)  # New black rectangle
        draw2.text((10, 60), "V2 Partial Test", fill=0)
        
        buf2 = epd.getbuffer(image2)
        epd.display_Partial(buf2)
        print("Partial refresh complete")
        time.sleep(3)
        
        # Test multiple partial refreshes
        print("Testing multiple partial refreshes...")
        for i in range(5):
            image3 = Image.new('1', (epd.width, epd.height), 255)
            draw3 = ImageDraw.Draw(image3)
            draw3.text((10, 100), f"Count: {i}", fill=0)
            buf3 = epd.getbuffer(image3)
            epd.display_Partial(buf3)
            print(f"  Partial refresh {i+1}/5")
            time.sleep(1)
        
        # Final clear
        print("Clearing display...")
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
    success = test_v2_driver()
    sys.exit(0 if success else 1)

