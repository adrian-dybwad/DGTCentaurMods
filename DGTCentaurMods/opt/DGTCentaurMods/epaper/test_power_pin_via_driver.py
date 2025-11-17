#!/usr/bin/env python3
"""
Test pins by using them as PWR_PIN in the epaper driver.
If a pin controls power, using it incorrectly will cause the board to crash.
Uses watchdog file to detect crashes.
"""

import os
import time
import sys
from pathlib import Path

# Watchdog file
WATCHDOG_FILE = Path("/tmp/power_pin_driver_test_watchdog")

def update_watchdog():
    """Update watchdog file."""
    try:
        WATCHDOG_FILE.write_text(f"{time.time()}\n")
    except:
        pass

def test_pin_as_pwr_pin(pin):
    """Test a pin by using it as PWR_PIN in the driver."""
    print(f"\n{'='*60}")
    print(f"Testing pin {pin} as PWR_PIN")
    print(f"{'='*60}")
    update_watchdog()
    
    # Set environment variable
    os.environ['EPAPER_PWR_PIN'] = str(pin)
    print(f"Set EPAPER_PWR_PIN={pin}")
    update_watchdog()
    
    # Try to initialize the driver
    print("Attempting to initialize epaper driver...")
    update_watchdog()
    
    try:
        # Import and test
        sys.path.insert(0, str(Path(__file__).parent))
        from epaper import DisplayManager
        
        print("Creating DisplayManager...")
        update_watchdog()
        display = DisplayManager()
        
        print("Calling display.init()...")
        update_watchdog()
        
        # This is where it might crash if pin controls power
        display.init()
        update_watchdog()
        
        print("  SUCCESS: Driver initialized with pin {pin} as PWR_PIN")
        print("  Pin {pin} is likely safe to use as PWR_PIN")
        
        # Try to shutdown
        print("Shutting down...")
        update_watchdog()
        display.shutdown()
        update_watchdog()
        
        return True
        
    except Exception as e:
        print(f"  ERROR: {e}")
        print(f"  This might indicate pin {pin} controls power")
        update_watchdog()
        return False
    finally:
        # Clean up environment
        if 'EPAPER_PWR_PIN' in os.environ:
            del os.environ['EPAPER_PWR_PIN']
        update_watchdog()

def main():
    print("=" * 60)
    print("POWER PIN TEST VIA DRIVER")
    print("=" * 60)
    print("""
This script tests pins by using them as PWR_PIN in the epaper driver.
If a pin controls board power, the board may crash during init.

Monitor the watchdog file from another terminal:
  watch -n 0.5 'cat /tmp/power_pin_driver_test_watchdog'

If the watchdog stops updating, note which pin was being tested.
""")
    
    # Pins to test (exclude known input pins like BUSY_PIN=24)
    # Test only output pins that could potentially control power
    test_pins = [7, 12, 16, 18]  # Excluded 24 (BUSY_PIN - input)
    
    input("Press Enter to start (or Ctrl+C to abort)...")
    
    update_watchdog()
    
    for pin in test_pins:
        print(f"\n\nTesting pin {pin}...")
        update_watchdog()
        
        success = test_pin_as_pwr_pin(pin)
        update_watchdog()
        
        if not success:
            print(f"\n*** WARNING: Pin {pin} may control power! ***")
            print("Board may have crashed. Check watchdog file.")
            break
        
        # Small delay between tests
        time.sleep(2)
        update_watchdog()
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("If board crashed, check which pin was being tested.")
    print("That pin likely controls board power.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest aborted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

