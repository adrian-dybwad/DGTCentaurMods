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
        
        # Test fast refresh
        print("Testing fast refresh...")
        epd.init_Fast()
        blackimage2 = Image.new('1', (epd.width, epd.height), 255)
        draw2 = ImageDraw.Draw(blackimage2)
        draw2.rectangle([10, 10, 50, 50], fill=255)  # White rectangle (erase)
        draw2.rectangle([60, 10, 100, 50], fill=0)  # New black rectangle
        draw2.text((10, 60), "V4 Fast Test", fill=0)
        
        blackbuf2 = epd.getbuffer(blackimage2)
        epd.display_Fast(blackbuf2, None)
        print("Fast refresh complete")
        time.sleep(3)
        
        # Test base refresh
        print("Testing base refresh...")
        epd.init()
        blackimage3 = Image.new('1', (epd.width, epd.height), 255)
        draw3 = ImageDraw.Draw(blackimage3)
        draw3.rectangle([10, 10, 50, 50], fill=255)  # White rectangle
        draw3.rectangle([110, 10, 150, 50], fill=0)  # New black rectangle
        draw3.text((10, 60), "V4 Base Test", fill=0)
        
        blackbuf3 = epd.getbuffer(blackimage3)
        epd.display_Base(blackbuf3, None)
        print("Base refresh complete")
        time.sleep(3)
        
        # Test partial refresh
        print("Testing partial refresh...")
        blackimage4 = Image.new('1', (epd.width, epd.height), 255)
        draw4 = ImageDraw.Draw(blackimage4)
        draw4.text((10, 100), "V4 Partial Test", fill=0)
        
        blackbuf4 = epd.getbuffer(blackimage4)
        # Partial update: Xstart, Ystart, Xend, Yend
        epd.display_Partial(blackbuf4, 0, 100, epd.width, 120)
        print("Partial refresh complete")
        time.sleep(2)
        
        # Test multiple partial refreshes
        print("Testing multiple partial refreshes...")
        for i in range(5):
            blackimage5 = Image.new('1', (epd.width, epd.height), 255)
            draw5 = ImageDraw.Draw(blackimage5)
            draw5.rectangle([10, 130, 100, 150], fill=255)  # Clear previous
            draw5.text((10, 130), f"Count: {i}", fill=0)
            blackbuf5 = epd.getbuffer(blackimage5)
            epd.display_Partial(blackbuf5, 0, 130, epd.width, 150)
            print(f"  Partial refresh {i+1}/5")
            time.sleep(1)
        
        # Test clear fast
        print("Testing fast clear...")
        epd.init_Fast()
        epd.Clear_Fast()
        print("Fast clear complete")
        time.sleep(2)
        
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

