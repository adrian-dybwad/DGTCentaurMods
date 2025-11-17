#!/usr/bin/env python3
"""
Minimal test script to diagnose ePaper driver issues.
Tests basic functionality step by step.
"""

import logging
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from PIL import Image
from epaper.driver import Driver

def test_driver():
    """Test the driver with a simple black screen."""
    print("=" * 60)
    print("ePaper Driver Diagnostic Test")
    print("=" * 60)
    
    try:
        print("\n1. Creating driver...")
        driver = Driver()
        print(f"   ✓ Driver created (width={driver.width}, height={driver.height})")
        
        print("\n2. Resetting display...")
        driver.reset()
        print("   ✓ Reset complete")
        time.sleep(0.1)
        
        print("\n3. Initializing display...")
        driver.init()
        print("   ✓ Initialization complete")
        time.sleep(0.5)
        
        print("\n4. Creating test image (all BLACK)...")
        # Create a simple black image
        test_image = Image.new("1", (driver.width, driver.height), 0)  # 0 = black
        print(f"   ✓ Image created: {test_image.size}, mode={test_image.mode}")
        
        print("\n5. Performing full refresh (this should take ~2 seconds)...")
        refresh_start = time.time()
        driver.full_refresh(test_image)
        refresh_duration = time.time() - refresh_start
        print(f"   ✓ Full refresh complete in {refresh_duration:.2f}s")
        
        if refresh_duration < 1.0:
            print("   ⚠️  WARNING: Refresh was too fast - display may not have updated")
        elif refresh_duration > 5.0:
            print("   ⚠️  WARNING: Refresh was too slow - may have timed out")
        else:
            print("   ✓ Refresh duration looks correct")
        
        print("\n6. Waiting 3 seconds to see if display updates...")
        time.sleep(3)
        
        print("\n7. Creating white image and refreshing...")
        white_image = Image.new("1", (driver.width, driver.height), 255)  # 255 = white
        refresh_start = time.time()
        driver.full_refresh(white_image)
        refresh_duration = time.time() - refresh_start
        print(f"   ✓ White refresh complete in {refresh_duration:.2f}s")
        
        print("\n8. Shutting down...")
        driver.sleep()
        driver.shutdown()
        print("   ✓ Shutdown complete")
        
        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)
        print("\nDid you see:")
        print("  - A black screen after step 5?")
        print("  - A white screen after step 7?")
        print("\nIf not, check the logs above for errors.")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_driver()

