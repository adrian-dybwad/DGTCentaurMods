#!/usr/bin/env python3
"""
Reset the ePaper display to pure white state.
Copy-paste friendly script.
"""

import sys
import os

# Add path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from epaper.framework.waveshare.epd2in9d import EPD

def reset_display_to_white():
    """Reset display to pure white."""
    print("Initializing display...")
    epd = EPD()
    result = epd.init()
    if result != 0:
        print("ERROR: Failed to initialize display")
        return
    
    print("Clearing display to white...")
    epd.Clear()
    
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

