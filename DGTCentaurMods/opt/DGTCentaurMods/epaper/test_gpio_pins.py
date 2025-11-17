#!/usr/bin/env python3
"""
Test if GPIO pins are actually toggling by monitoring them.
This helps verify the pins are connected correctly.
"""

import sys
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

try:
    import RPi.GPIO as GPIO
    import time
except ImportError as e:
    print(f"ERROR: {e}")
    print("This script must be run on Raspberry Pi with RPi.GPIO installed")
    sys.exit(1)

def test_gpio_pins():
    """Test if GPIO pins can be toggled."""
    print("=" * 60)
    print("GPIO Pin Toggle Test")
    print("=" * 60)
    
    # Pins to test
    pins = {
        'RST': 17,
        'DC': 25,
        'CS': 8,  # Try both 8 and 1
        'BUSY': 24,
    }
    
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    print("\nTesting pin toggling...")
    print("Watch the display - you should see a reset flash when RST toggles LOW")
    print()
    
    for name, pin in pins.items():
        try:
            print(f"Testing {name} (GPIO {pin})...")
            GPIO.setup(pin, GPIO.OUT)
            
            # Toggle a few times
            for i in range(3):
                GPIO.output(pin, GPIO.LOW)
                time.sleep(0.1)
                GPIO.output(pin, GPIO.HIGH)
                time.sleep(0.1)
            
            print(f"  ✓ {name} (GPIO {pin}) toggled successfully")
        except Exception as e:
            print(f"  ✗ {name} (GPIO {pin}) failed: {e}")
    
    print("\nTesting RST pin reset sequence...")
    print("This should cause a visible reset on the display if connected correctly")
    rst_pin = pins['RST']
    GPIO.setup(rst_pin, GPIO.OUT)
    
    print("  Setting RST LOW (reset)...")
    GPIO.output(rst_pin, GPIO.LOW)
    time.sleep(0.02)
    print("  Setting RST HIGH (release reset)...")
    GPIO.output(rst_pin, GPIO.HIGH)
    time.sleep(0.02)
    print("  ✓ Reset sequence complete")
    print("  Did you see the display reset? (It should flash briefly)")
    
    print("\nTesting CS pin (GPIO 8)...")
    try:
        cs_pin = 8
        GPIO.setup(cs_pin, GPIO.OUT)
        GPIO.output(cs_pin, GPIO.HIGH)  # CS is active LOW, so HIGH = deselected
        print(f"  ✓ CS pin (GPIO {cs_pin}) set to HIGH (deselected)")
    except Exception as e:
        print(f"  ✗ CS pin (GPIO {cs_pin}) failed: {e}")
    
    print("\nTesting CS pin (GPIO 1) - alternative...")
    try:
        cs_pin = 1
        GPIO.setup(cs_pin, GPIO.OUT)
        GPIO.output(cs_pin, GPIO.HIGH)
        print(f"  ✓ CS pin (GPIO {cs_pin}) set to HIGH (deselected)")
    except Exception as e:
        print(f"  ✗ CS pin (GPIO {cs_pin}) failed: {e}")
    
    GPIO.cleanup()
    print("\nDone!")

if __name__ == "__main__":
    test_gpio_pins()

