#!/usr/bin/env python3
"""
Safely test GPIO pins to identify which one controls board power.
Tests pins one at a time and checks if the board becomes unresponsive.
"""

import subprocess
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

def test_board_responsive():
    """Test if the board is still responsive by reading a safe GPIO pin."""
    try:
        # Try to read a pin that shouldn't affect anything (pin 2, I2C SDA, usually safe)
        GPIO.setup(2, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        state = GPIO.input(2)
        GPIO.cleanup(2)
        return True
    except Exception as e:
        print(f"  Board responsiveness test failed: {e}")
        return False

def test_epaper_responsive():
    """Test if epaper driver is still accessible."""
    try:
        from ctypes import CDLL
        so_path = Path("/opt/DGTCentaurMods/display/epaperDriver.so")
        if not so_path.exists():
            return False
        
        dll = CDLL(str(so_path))
        # Just try to access the library, don't call any functions
        return dll is not None
    except Exception as e:
        print(f"  Epaper responsiveness test failed: {e}")
        return False

def test_pin_safely(pin):
    """Test a single pin to see if it controls power."""
    print(f"\n{'='*60}")
    print(f"Testing pin {pin}")
    print(f"{'='*60}")
    
    try:
        # First, check if board is responsive
        print("1. Checking board responsiveness (before test)...")
        if not test_board_responsive():
            print("  WARNING: Board already unresponsive!")
            return False
        
        # Read initial state
        print(f"2. Reading initial state of pin {pin}...")
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        initial_state = GPIO.input(pin)
        print(f"  Initial state: {initial_state}")
        
        # Switch to output mode
        print(f"3. Setting pin {pin} to OUTPUT mode...")
        GPIO.setup(pin, GPIO.OUT)
        
        # Set to HIGH
        print(f"4. Setting pin {pin} to HIGH...")
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(0.1)  # Brief pause
        
        # Check responsiveness
        print("5. Checking board responsiveness (after HIGH)...")
        if not test_board_responsive():
            print(f"  *** BOARD BECAME UNRESPONSIVE AFTER SETTING PIN {pin} HIGH ***")
            print(f"  *** PIN {pin} LIKELY CONTROLS POWER (HIGH = POWER ON) ***")
            return True
        
        # Set to LOW
        print(f"6. Setting pin {pin} to LOW...")
        GPIO.output(pin, GPIO.LOW)
        time.sleep(0.1)  # Brief pause
        
        # Check responsiveness
        print("7. Checking board responsiveness (after LOW)...")
        if not test_board_responsive():
            print(f"  *** BOARD BECAME UNRESPONSIVE AFTER SETTING PIN {pin} LOW ***")
            print(f"  *** PIN {pin} LIKELY CONTROLS POWER (LOW = POWER OFF) ***")
            return True
        
        # Restore to initial state
        print(f"8. Restoring pin {pin} to initial state ({initial_state})...")
        GPIO.output(pin, initial_state)
        time.sleep(0.1)
        
        # Final responsiveness check
        print("9. Final board responsiveness check...")
        if not test_board_responsive():
            print(f"  *** BOARD BECAME UNRESPONSIVE AFTER RESTORING PIN {pin} ***")
            return True
        
        print(f"  Pin {pin} test completed - board still responsive")
        return False
        
    except Exception as e:
        print(f"  ERROR testing pin {pin}: {e}")
        return False
    finally:
        # Try to restore pin to input mode
        try:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except:
            pass

def main():
    print("=" * 60)
    print("SAFE POWER PIN IDENTIFICATION TEST")
    print("=" * 60)
    print("""
WARNING: This script will test GPIO pins that might control board power.
If a pin controls power, the board may become unresponsive.
Test pins one at a time and monitor for responsiveness.

Press Ctrl+C to abort at any time.
""")
    
    input("Press Enter to continue (or Ctrl+C to abort)...")
    
    power_pins = []
    
    for pin in TEST_PINS:
        print(f"\n\nTesting pin {pin}...")
        is_power = test_pin_safely(pin)
        
        if is_power:
            power_pins.append(pin)
            print(f"\n*** PIN {pin} IDENTIFIED AS POWER CONTROL PIN ***")
            print("STOPPING TESTS TO PREVENT FURTHER BOARD CRASHES")
            break
        
        # Small delay between tests
        time.sleep(0.5)
    
    # Cleanup
    try:
        GPIO.cleanup()
    except:
        pass
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    if power_pins:
        print(f"\nPOWER CONTROL PINS IDENTIFIED: {power_pins}")
        print("\nWARNING: These pins control board power!")
        print("Do NOT toggle these pins in normal operation.")
    else:
        print("\nNo power control pins identified in tested pins.")
        print("Power may be controlled elsewhere or always on.")
    
    print("\nTested pins:", TEST_PINS)

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

