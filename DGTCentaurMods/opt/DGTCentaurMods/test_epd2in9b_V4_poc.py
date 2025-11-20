#!/usr/bin/env python3
"""
POC test for epd2in9b_V4 driver compatibility.
Tests if the V4 driver works with the display hardware in monochrome mode.
"""

import sys
import os
import time
from pathlib import Path
from PIL import Image, ImageDraw

# Get script directory
SCRIPT_DIR = Path(__file__).resolve().parent

# Add script directory to path to import local epd2in9b_V4
sys.path.insert(0, str(SCRIPT_DIR))

# Import the local copy of epd2in9b_V4
import epd2in9b_V4

# Import our epdconfig (epd2in9b_V4 will use it via fallback)
from epaper.framework.waveshare import epdconfig


def test_v4_driver():
    """Test the epd2in9b_V4 driver."""
    print("Testing epd2in9b_V4 driver...")
    
    try:
        # Initialize display
        epd = epd2in9b_V4.EPD()
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
        
        # Test full refresh (monochrome - black only)
        print("Testing full refresh (monochrome)...")
        blackimage = Image.new('1', (epd.width, epd.height), 255)  # White
        draw = ImageDraw.Draw(blackimage)
        draw.rectangle([10, 10, 50, 50], fill=0)  # Black rectangle
        draw.text((10, 60), "V4 Full Test", fill=0)
        
        blackbuf = epd.getbuffer(blackimage)
        epd.display(blackbuf, None)  # Only black image, no red/yellow
        print("Full refresh complete")
        time.sleep(3)
        
        # Test fast refresh (using horizontal orientation like the example)
        print("Testing fast refresh (horizontal orientation)...")
        epd.init_Fast()
        # Horizontal image: (height, width) = (296, 128)
        HBlackimage = Image.new('1', (epd.height, epd.width), 255)
        draw2 = ImageDraw.Draw(HBlackimage)
        draw2.text((10, 0), 'V4 Fast Test', fill=0)
        draw2.text((10, 20), '2.9inch e-Paper b V4', fill=0)
        draw2.line((20, 50, 70, 100), fill=0)
        draw2.line((70, 50, 20, 100), fill=0)
        draw2.rectangle((20, 50, 70, 100), outline=0)
        
        blackbuf2 = epd.getbuffer(HBlackimage)
        epd.display_Fast(blackbuf2, None)
        print("Fast refresh complete")
        time.sleep(3)
        
        # Test partial refresh (following example pattern)
        print("Testing partial refresh...")
        epd.init()
        # Use display_Base_color before partial updates (as shown in example)
        epd.display_Base_color(0xFF)
        # Horizontal image for partial updates
        HBlackimage2 = Image.new('1', (epd.height, epd.width), 255)
        draw3 = ImageDraw.Draw(HBlackimage2)
        draw3.rectangle((10, 10, 120, 50), fill=255)
        draw3.text((10, 10), "V4 Partial Test", fill=0)
        
        blackbuf3 = epd.getbuffer(HBlackimage2)
        # Partial update coordinates: Xstart, Ystart, Xend, Yend
        # Following example: epd.display_Partial(..., 10, epd.height - 120, 50, epd.height - 10)
        epd.display_Partial(blackbuf3, 10, epd.height - 120, 50, epd.height - 10)
        print("Partial refresh complete")
        time.sleep(2)
        
        # Test multiple partial refreshes (time display pattern from example)
        print("Testing multiple partial refreshes...")
        for i in range(5):
            HBlackimage3 = Image.new('1', (epd.height, epd.width), 255)
            draw4 = ImageDraw.Draw(HBlackimage3)
            draw4.rectangle((10, 10, 120, 50), fill=255)
            # Simulate time display
            draw4.text((10, 10), f"Count: {i:02d}", fill=0)
            newimage = HBlackimage3.crop([10, 10, 120, 50])
            HBlackimage3.paste(newimage, (10, 10))
            blackbuf4 = epd.getbuffer(HBlackimage3)
            epd.display_Partial(blackbuf4, 10, epd.height - 120, 50, epd.height - 10)
            print(f"  Partial refresh {i+1}/5")
            time.sleep(1)
        
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
    success = test_v4_driver()
    sys.exit(0 if success else 1)

