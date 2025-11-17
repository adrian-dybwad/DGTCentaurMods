#!/usr/bin/env python3
"""
Safely test GPIO pins by ONLY READING them (no output mode).
Uses a watchdog file to detect if the board becomes unresponsive.
Run this script and monitor from another terminal or system.
"""

import time
import sys
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
except ImportError:
    print("ERROR: RPi.GPIO not available")
    sys.exit(1)

# Pins to test (exclude known input pins like BUSY_PIN=24)
# Test only output pins that could potentially control power
TEST_PINS = [7, 12, 16, 18]  # Excluded 24 (BUSY_PIN - input)

# Watchdog file - update this periodically
WATCHDOG_FILE = Path("/tmp/power_pin_test_watchdog")

def update_watchdog():
    """Update watchdog file to show we're still alive."""
    try:
        WATCHDOG_FILE.write_text(f"{time.time()}\n")
    except:
        pass

def test_pin_readonly(pin):
    """Test a pin by ONLY reading it (no output mode)."""
    print(f"Testing pin {pin} (READ ONLY)...")
    update_watchdog()
    
    try:
        # Set to input with pull-up (safe, read-only)
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        state = GPIO.input(pin)
        print(f"  Pin {pin} state: {state}")
        update_watchdog()
        return True
    except Exception as e:
        print(f"  ERROR reading pin {pin}: {e}")
        return False

def main():
    print("=" * 60)
    print("READ-ONLY POWER PIN TEST")
    print("=" * 60)
    print("""
This script ONLY READS pins (no output mode).
It updates a watchdog file every second.
Monitor /tmp/power_pin_test_watchdog from another terminal:
  watch -n 1 'cat /tmp/power_pin_test_watchdog'

If the watchdog stops updating, the board may have crashed.
""")
    
    # Initialize watchdog
    update_watchdog()
    print(f"Watchdog file: {WATCHDOG_FILE}")
    print("Starting tests in 3 seconds...")
    time.sleep(3)
    
    for pin in TEST_PINS:
        print(f"\n--- Testing pin {pin} ---")
        update_watchdog()
        
        if not test_pin_readonly(pin):
            print(f"  Failed to read pin {pin}")
        
        time.sleep(1)
        update_watchdog()
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("All pins tested in read-only mode.")
    print("If board crashed, check which pin was being tested.")
    
    # Keep watchdog alive for a bit
    for i in range(5):
        time.sleep(1)
        update_watchdog()
    
    try:
        GPIO.cleanup()
    except:
        pass

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest aborted by user")
        try:
            GPIO.cleanup()
        except:
            pass
        sys.exit(0)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        try:
            GPIO.cleanup()
        except:
            pass
        sys.exit(1)

