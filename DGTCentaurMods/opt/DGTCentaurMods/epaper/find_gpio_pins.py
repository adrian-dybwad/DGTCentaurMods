#!/usr/bin/env python3
"""
Helper script to find GPIO pins used by epaperDriver.so.

This script loads epaperDriver.so and monitors GPIO pin changes
to determine which pins are actually used.
"""

import sys
from pathlib import Path

# Add parent directory to path
script_dir = Path(__file__).resolve().parent
parent_dir = script_dir.parent
sys.path.insert(0, str(parent_dir))

try:
    import RPi.GPIO as GPIO
    from ctypes import CDLL
    import time
except ImportError as e:
    print(f"ERROR: {e}")
    print("This script must be run on Raspberry Pi with RPi.GPIO installed")
    sys.exit(1)

def monitor_gpio_pins():
    """Monitor GPIO pins while epaperDriver.so is running."""
    print("=" * 60)
    print("GPIO Pin Detection for epaperDriver.so")
    print("=" * 60)
    
    # Find epaperDriver.so
    possible_paths = [
        Path("/opt/DGTCentaurMods/epaper/epaperDriver.so"),
        parent_dir / "display" / "epaperDriver.so",
        parent_dir.parent / "display" / "epaperDriver.so",
    ]
    
    lib_path = None
    for path in possible_paths:
        if path.exists():
            lib_path = path
            break
    
    if not lib_path:
        print("ERROR: epaperDriver.so not found")
        print("Searched in:")
        for path in possible_paths:
            print(f"  - {path}")
        return
    
    print(f"\nFound epaperDriver.so at: {lib_path}")
    
    # Initialize GPIO monitoring
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    # Monitor common GPIO pins
    pins_to_monitor = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
    
    print(f"\nMonitoring {len(pins_to_monitor)} GPIO pins...")
    print("Setting up pins as inputs with pull-up...")
    
    initial_states = {}
    for pin in pins_to_monitor:
        try:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            initial_states[pin] = GPIO.input(pin)
        except Exception as e:
            print(f"  Pin {pin}: Cannot monitor ({e})")
    
    print("\nLoading epaperDriver.so...")
    dll = CDLL(str(lib_path))
    
    print("Calling openDisplay()...")
    dll.openDisplay()
    
    print("Calling reset()...")
    dll.reset()
    time.sleep(0.1)
    
    print("Calling init()...")
    dll.init()
    time.sleep(0.1)
    
    print("\nChecking pin states after operations...")
    changed_pins = []
    for pin in pins_to_monitor:
        if pin in initial_states:
            try:
                current_state = GPIO.input(pin)
                if current_state != initial_states[pin]:
                    changed_pins.append((pin, initial_states[pin], current_state))
                    print(f"  Pin {pin}: {initial_states[pin]} -> {current_state}")
            except:
                pass
    
    if changed_pins:
        print(f"\n✓ Found {len(changed_pins)} pins that changed:")
        for pin, old, new in changed_pins:
            print(f"  GPIO {pin}: {old} -> {new}")
    else:
        print("\n⚠ No pins changed (might be using hardware SPI CS)")
    
    print("\nCleaning up...")
    try:
        dll.powerOffDisplay()
    except:
        pass
    
    GPIO.cleanup()
    print("Done!")

if __name__ == "__main__":
    monitor_gpio_pins()

