#!/usr/bin/env python3
"""
Reset the ePaper display to pure white state.
Copy-paste friendly script.
"""

import sys
import os

# Add path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DGTCentaurMods.epaper.framework.waveshare import epd2in9d
from PIL import Image

def reset_display_to_white():
    """Reset display to pure white using display() with white image."""
    print("Initializing display...")
    epd = epd2in9d.EPD()
    result = epd.init()
    if result != 0:
        print("ERROR: Failed to initialize display")
        return
    
    print("Clearing display to white...")
    # Create a white image and display it
    white_image = Image.new("1", (epd.width, epd.height), 255)  # 255 = white
    buf = epd.getbuffer(white_image)
    epd.display(buf)
    
    print("Display reset to white. Putting display to sleep...")
    epd.sleep()
    
    print("Done!")

if __name__ == "__main__":
    try:
        reset_display_to_white()
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
