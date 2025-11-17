#!/usr/bin/env python3
"""
Comprehensive GPIO pin monitoring to identify all ePaper pins including PWR_PIN.
Monitors all GPIO pins (0-27) while the old driver runs.
"""

import subprocess
import time
import sys
from pathlib import Path
from threading import Thread
from collections import defaultdict

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
    USE_GPIOZERO = False
except ImportError:
    print("WARNING: RPi.GPIO not available. Trying gpiozero...")
    try:
        import gpiozero
        GPIO_AVAILABLE = True
        USE_GPIOZERO = True
    except ImportError:
        print("ERROR: Neither RPi.GPIO nor gpiozero available.")
        print("Install with: sudo apt-get install python3-rpi.gpio")
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

# Monitor all GPIO pins (0-27 for Raspberry Pi)
ALL_GPIO_PINS = list(range(28))  # GPIO 0-27

# Known pins (to exclude from "unknown" category)
KNOWN_PINS = {
    12: "RST",
    16: "DC", 
    18: "CS",
    24: "BUSY",
    10: "MOSI (SPI)",
    11: "SCLK (SPI)",
}

# Global state
pin_states = {}
pin_initial_states = {}
monitoring = True
changes_detected = []
pin_change_counts = defaultdict(int)
pin_timing = defaultdict(list)

def monitor_pin(pin):
    """Monitor a single GPIO pin for state changes."""
    global pin_states, pin_initial_states, changes_detected, pin_change_counts, pin_timing
    
    if USE_GPIOZERO:
        try:
            from gpiozero import DigitalInputDevice
            device = DigitalInputDevice(pin, pull_up=True)
        except Exception as e:
            return
    else:
        try:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except Exception as e:
            return
    
    last_state = None
    first_read = True
    
    while monitoring:
        try:
            if USE_GPIOZERO:
                current_state = device.value
            else:
                current_state = GPIO.input(pin)
            
            if first_read:
                pin_initial_states[pin] = current_state
                pin_states[pin] = current_state
                first_read = False
            
            pin_states[pin] = current_state
            
            if last_state is not None and current_state != last_state:
                timestamp = time.time()
                change = {
                    'pin': pin,
                    'timestamp': timestamp,
                    'from': last_state,
                    'to': current_state
                }
                changes_detected.append(change)
                pin_change_counts[pin] += 1
                pin_timing[pin].append(timestamp)
                
                pin_name = KNOWN_PINS.get(pin, f"GPIO{pin}")
                print(f"[{timestamp:.3f}] {pin_name} (pin {pin}): {last_state} -> {current_state}")
            
            last_state = current_state
            time.sleep(0.005)  # Check every 5ms for better resolution
        except Exception as e:
            # Some pins may not be accessible
            break

def run_old_driver(so_path):
    """Run the old driver to trigger GPIO activity."""
    print("=" * 60)
    print("RUNNING OLD DRIVER")
    print("=" * 60)
    
    test_script = f"""
from ctypes import CDLL
import time

dll = CDLL('{so_path}')
print("Opening display...")
dll.openDisplay()
print("Initializing display...")
dll.init()
print("Performing display operation...")
# Create a simple test image
width, height = 128, 296
buf = [0xFF] * (width * height // 8)
dll.display(bytes(buf))
print("Waiting 2 seconds...")
time.sleep(2)
print("Closing display...")
dll.closeDisplay()
print("Done!")
"""
    
    test_file = Path("/tmp/monitor_all_pins_test.py")
    test_file.write_text(test_script)
    
    try:
        result = subprocess.run(
            ["python3", str(test_file)],
            capture_output=True,
            text=True,
            timeout=15
        )
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("ERROR: Driver test timed out")
        return False
    except Exception as e:
        print(f"ERROR running driver: {e}")
        return False

def analyze_pin_behavior():
    """Analyze pin behavior to identify their functions."""
    print("\n" + "=" * 60)
    print("PIN FUNCTION ANALYSIS")
    print("=" * 60)
    
    # Group pins by behavior
    power_candidates = []  # Pins that go HIGH at start, LOW during operation, HIGH at end
    control_pins = []      # Pins that toggle frequently
    static_pins = []       # Pins that don't change
    
    for pin in ALL_GPIO_PINS:
        if pin not in pin_states:
            continue
        
        changes = pin_change_counts[pin]
        initial = pin_initial_states.get(pin)
        final = pin_states.get(pin)
        
        if changes == 0:
            static_pins.append((pin, initial))
        elif changes >= 5:
            control_pins.append((pin, changes))
        
        # Look for power pin pattern: HIGH initially, goes LOW during operation
        if initial == 1 and final == 0:
            power_candidates.append(pin)
        elif initial == 0 and final == 1:
            # Power might be inverted
            power_candidates.append(pin)
    
    print("\nControl Pins (frequent toggling):")
    control_pins.sort(key=lambda x: x[1], reverse=True)
    for pin, count in control_pins[:10]:
        pin_name = KNOWN_PINS.get(pin, f"GPIO{pin}")
        print(f"  {pin_name} (pin {pin}): {count} changes")
    
    print("\nPower Pin Candidates (state change during operation):")
    for pin in power_candidates:
        pin_name = KNOWN_PINS.get(pin, f"GPIO{pin}")
        initial = pin_initial_states.get(pin)
        final = pin_states.get(pin)
        changes = pin_change_counts[pin]
        print(f"  {pin_name} (pin {pin}): {initial} -> {final} ({changes} changes)")
    
    print("\nStatic Pins (no changes):")
    for pin, state in static_pins[:10]:
        pin_name = KNOWN_PINS.get(pin, f"GPIO{pin}")
        print(f"  {pin_name} (pin {pin}): {state} (static)")

def main():
    global monitoring
    
    so_path = find_so_file()
    if not so_path:
        print("ERROR: Could not find epaperDriver.so")
        sys.exit(1)
    
    print("=" * 60)
    print("COMPREHENSIVE GPIO PIN MONITORING")
    print("=" * 60)
    print(f"Driver: {so_path}")
    print(f"Monitoring GPIO pins: 0-27")
    print(f"Known pins: {KNOWN_PINS}")
    print()
    
    # Setup GPIO
    if USE_GPIOZERO:
        print("Using gpiozero for GPIO access")
    else:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        print("Using RPi.GPIO for GPIO access")
    
    # Setup monitoring threads for all pins
    monitor_threads = []
    accessible_pins = []
    
    print("Setting up pin monitoring...")
    for pin in ALL_GPIO_PINS:
        try:
            thread = Thread(target=monitor_pin, args=(pin,), daemon=True)
            thread.start()
            monitor_threads.append(thread)
            accessible_pins.append(pin)
        except Exception as e:
            pass  # Some pins may not be accessible
    
    print(f"Monitoring {len(accessible_pins)} accessible pins")
    
    print("\n" + "=" * 60)
    print("STARTING MONITORING")
    print("=" * 60)
    print("Waiting for pins to settle...")
    time.sleep(0.2)
    
    print("\nInitial pin states (non-zero/one states):")
    for pin in sorted(accessible_pins):
        if pin in pin_initial_states:
            state = pin_initial_states[pin]
            pin_name = KNOWN_PINS.get(pin, f"GPIO{pin}")
            if state != 1:  # Show non-HIGH states
                print(f"  {pin_name} (pin {pin}): {state}")
    
    print("\nRunning old driver...")
    print("Watch for pin state changes below:\n")
    
    # Run the old driver
    driver_start = time.time()
    run_old_driver(so_path)
    driver_end = time.time()
    
    # Continue monitoring for a bit after driver finishes
    print("\nContinuing to monitor for 3 more seconds...")
    time.sleep(3)
    
    monitoring = False
    
    # Wait for threads to finish
    for thread in monitor_threads:
        thread.join(timeout=1.0)
    
    # Cleanup
    if not USE_GPIOZERO:
        GPIO.cleanup()
    
    # Analysis
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    print(f"\nTotal pin state changes detected: {len(changes_detected)}")
    print(f"Pins with changes: {len(pin_change_counts)}")
    
    print("\nMost Active Pins:")
    active_pins = sorted(pin_change_counts.items(), key=lambda x: x[1], reverse=True)
    for pin, count in active_pins[:15]:
        pin_name = KNOWN_PINS.get(pin, f"GPIO{pin}")
        print(f"  {pin_name} (pin {pin}): {count} changes")
    
    # Detailed analysis
    analyze_pin_behavior()
    
    print("\n" + "=" * 60)
    print("FINAL PIN STATES")
    print("=" * 60)
    print("Pins that changed state:")
    for pin in sorted(pin_change_counts.keys()):
        pin_name = KNOWN_PINS.get(pin, f"GPIO{pin}")
        initial = pin_initial_states.get(pin, "?")
        final = pin_states.get(pin, "?")
        changes = pin_change_counts[pin]
        if initial != final:
            print(f"  {pin_name} (pin {pin}): {initial} -> {final} ({changes} changes)")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        monitoring = False
        if not USE_GPIOZERO:
            GPIO.cleanup()
        sys.exit(0)

