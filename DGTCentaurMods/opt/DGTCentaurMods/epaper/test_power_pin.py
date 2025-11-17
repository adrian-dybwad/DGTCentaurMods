#!/usr/bin/env python3
"""
Test if pin 7 is the PWR_PIN by monitoring it during openDisplay/closeDisplay.
Power pin should go HIGH at openDisplay and LOW at closeDisplay.
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

def find_so_file():
    """Find the epaperDriver.so file."""
    locations = [
        Path("/opt/DGTCentaurMods/display/epaperDriver.so"),
        Path("/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/display/epaperDriver.so"),
    ]
    
    for loc in locations:
        if loc.exists():
            return loc
    return None

def monitor_pin_during_operation(pin, so_path):
    """Monitor a pin during openDisplay and closeDisplay."""
    print(f"Monitoring pin {pin} during openDisplay/closeDisplay operations...")
    
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Test script that separates openDisplay and closeDisplay
    test_script = f"""
from ctypes import CDLL
import time

dll = CDLL('{so_path}')

print("=== openDisplay() ===")
dll.openDisplay()
time.sleep(1)

print("=== init() ===")
dll.init()
time.sleep(1)

print("=== closeDisplay() ===")
dll.closeDisplay()
time.sleep(1)

print("Done!")
"""
    
    test_file = Path("/tmp/test_power_pin.py")
    test_file.write_text(test_script)
    
    # Monitor pin state
    print(f"\nInitial state (before openDisplay):")
    initial = GPIO.input(pin)
    print(f"  Pin {pin}: {initial}")
    
    # Start monitoring in background
    import threading
    states = []
    timestamps = []
    monitoring = True
    
    def monitor():
        while monitoring:
            state = GPIO.input(pin)
            states.append(state)
            timestamps.append(time.time())
            time.sleep(0.01)
    
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    
    # Run the test
    print("\nRunning driver operations...")
    result = subprocess.run(
        ["python3", str(test_file)],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    
    # Stop monitoring
    time.sleep(0.5)
    monitoring = False
    monitor_thread.join(timeout=1.0)
    
    # Analyze results
    print(f"\n=== Pin {pin} Analysis ===")
    print(f"Total samples: {len(states)}")
    
    if len(states) > 0:
        first_state = states[0]
        last_state = states[-1]
        
        # Find state changes
        changes = []
        for i in range(1, len(states)):
            if states[i] != states[i-1]:
                rel_time = timestamps[i] - timestamps[0]
                changes.append((rel_time, states[i-1], states[i]))
        
        print(f"Initial state: {first_state}")
        print(f"Final state: {last_state}")
        print(f"State changes: {len(changes)}")
        
        if changes:
            print("\nState change timeline:")
            for rel_time, from_state, to_state in changes[:10]:
                print(f"  {rel_time:.3f}s: {from_state} -> {to_state}")
        
        # Check for power pin pattern
        # Power pin should: go HIGH at openDisplay, stay HIGH, go LOW at closeDisplay
        print("\nPower pin pattern check:")
        if first_state == 0 and last_state == 0:
            print("  Pattern: LOW -> ... -> LOW")
            print("  Could be power pin if it goes HIGH during operation")
        elif first_state == 1 and last_state == 1:
            print("  Pattern: HIGH -> ... -> HIGH")
            print("  Could be power pin if it stays HIGH (always on)")
        elif first_state == 0 and last_state == 1:
            print("  Pattern: LOW -> ... -> HIGH")
            print("  Matches power-on pattern!")
        elif first_state == 1 and last_state == 0:
            print("  Pattern: HIGH -> ... -> LOW")
            print("  Matches power-off pattern!")
    
    GPIO.cleanup()
    return states

def main():
    so_path = find_so_file()
    if not so_path:
        print("ERROR: Could not find epaperDriver.so")
        sys.exit(1)
    
    print("=" * 60)
    print("POWER PIN IDENTIFICATION TEST")
    print("=" * 60)
    print(f"Driver: {so_path}\n")
    
    # Test pin 7 (showed activity in monitoring)
    print("Testing pin 7 (showed activity in previous monitoring):")
    states_7 = monitor_pin_during_operation(7, so_path)
    
    # Also test pin 18 (currently set as PWR_PIN)
    print("\n" + "=" * 60)
    print("Testing pin 18 (currently configured as PWR_PIN):")
    # Re-setup GPIO mode for second test
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    states_18 = monitor_pin_during_operation(18, so_path)
    
    print("\n" + "=" * 60)
    print("RECOMMENDATION")
    print("=" * 60)
    print("""
Look for a pin that:
1. Goes HIGH when openDisplay() is called
2. Stays HIGH during operation
3. Goes LOW when closeDisplay() is called

If no pin shows this pattern, the power may be:
- Always on (hardwired)
- Controlled elsewhere (not via GPIO)
- Using a different pin not in our test
""")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        GPIO.cleanup()
        sys.exit(0)

