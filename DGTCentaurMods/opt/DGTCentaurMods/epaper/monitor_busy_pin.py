#!/usr/bin/env python3
"""
Monitor GPIO pins while the old epaperDriver.so runs to identify the BUSY pin.
This monitors GPIO pin states and detects which pin changes during display operations.
"""

import subprocess
import time
import sys
from pathlib import Path
from threading import Thread
import signal

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
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
else:
    USE_GPIOZERO = False

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

# Pins to monitor (candidates for BUSY pin)
CANDIDATE_PINS = [13, 24, 25, 12, 16, 18]

# Global state
pin_states = {}
monitoring = True
changes_detected = []

def monitor_pin(pin):
    """Monitor a single GPIO pin for state changes."""
    global pin_states, changes_detected
    
    if USE_GPIOZERO:
        try:
            from gpiozero import DigitalInputDevice
            device = DigitalInputDevice(pin, pull_up=True)
        except:
            return
    
    last_state = None
    while monitoring:
        try:
            if USE_GPIOZERO:
                current_state = device.value
            else:
                current_state = GPIO.input(pin)
            
            pin_states[pin] = current_state
            
            if last_state is not None and current_state != last_state:
                timestamp = time.time()
                changes_detected.append({
                    'pin': pin,
                    'timestamp': timestamp,
                    'from': last_state,
                    'to': current_state
                })
                print(f"[{timestamp:.3f}] Pin {pin}: {last_state} -> {current_state}")
            
            last_state = current_state
            time.sleep(0.01)  # Check every 10ms
        except Exception as e:
            print(f"ERROR monitoring pin {pin}: {e}")
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
print("Waiting 3 seconds for operations...")
time.sleep(3)
print("Closing display...")
dll.closeDisplay()
print("Done!")
"""
    
    test_file = Path("/tmp/monitor_epaper_test.py")
    test_file.write_text(test_script)
    
    try:
        result = subprocess.run(
            ["python3", str(test_file)],
            capture_output=True,
            text=True,
            timeout=10
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

def main():
    global monitoring
    
    so_path = find_so_file()
    if not so_path:
        print("ERROR: Could not find epaperDriver.so")
        sys.exit(1)
    
    print(f"Monitoring GPIO pins while old driver runs")
    print(f"Driver: {so_path}")
    print(f"Candidate pins: {CANDIDATE_PINS}")
    print()
    
    # Setup GPIO
    if USE_GPIOZERO:
        print("Using gpiozero for GPIO access")
    else:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        print("Using RPi.GPIO for GPIO access")
    
    # Setup monitoring threads
    monitor_threads = []
    for pin in CANDIDATE_PINS:
        try:
            if not USE_GPIOZERO:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            thread = Thread(target=monitor_pin, args=(pin,), daemon=True)
            thread.start()
            monitor_threads.append(thread)
            print(f"Started monitoring pin {pin}")
        except Exception as e:
            print(f"WARNING: Could not monitor pin {pin}: {e}")
    
    print("\n" + "=" * 60)
    print("STARTING MONITORING")
    print("=" * 60)
    print("Initial pin states:")
    time.sleep(0.1)  # Let pins settle
    for pin in CANDIDATE_PINS:
        if pin in pin_states:
            print(f"  Pin {pin}: {pin_states[pin]}")
    
    print("\nRunning old driver...")
    print("Watch for pin state changes below:\n")
    
    # Run the old driver
    driver_start = time.time()
    run_old_driver(so_path)
    driver_end = time.time()
    
    # Continue monitoring for a bit after driver finishes
    print("\nContinuing to monitor for 2 more seconds...")
    time.sleep(2)
    
    monitoring = False
    
    # Wait for threads to finish
    for thread in monitor_threads:
        thread.join(timeout=0.5)
    
    # Cleanup
    if not USE_GPIOZERO:
        GPIO.cleanup()
    
    # Analysis
    print("\n" + "=" * 60)
    print("ANALYSIS")
    print("=" * 60)
    
    if not changes_detected:
        print("No pin state changes detected during driver operation.")
        print("This could mean:")
        print("  1. BUSY pin is not in the candidate list")
        print("  2. BUSY pin doesn't change state (always LOW or always HIGH)")
        print("  3. Driver uses a different method to check BUSY")
    else:
        print(f"Detected {len(changes_detected)} pin state changes:")
        print()
        
        # Group by pin
        pin_changes = {}
        for change in changes_detected:
            pin = change['pin']
            if pin not in pin_changes:
                pin_changes[pin] = []
            pin_changes[pin].append(change)
        
        for pin in sorted(pin_changes.keys()):
            changes = pin_changes[pin]
            print(f"Pin {pin}: {len(changes)} change(s)")
            for change in changes[:5]:  # Show first 5
                rel_time = change['timestamp'] - driver_start
                print(f"  {rel_time:.3f}s: {change['from']} -> {change['to']}")
            if len(changes) > 5:
                print(f"  ... and {len(changes) - 5} more")
        
        # Identify most likely BUSY pin
        print("\nMost active pins (likely BUSY candidates):")
        pin_activity = [(pin, len(changes)) for pin, changes in pin_changes.items()]
        pin_activity.sort(key=lambda x: x[1], reverse=True)
        for pin, count in pin_activity:
            print(f"  Pin {pin}: {count} changes")
    
    print("\n" + "=" * 60)
    print("FINAL PIN STATES")
    print("=" * 60)
    for pin in CANDIDATE_PINS:
        if pin in pin_states:
            print(f"  Pin {pin}: {pin_states[pin]}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        monitoring = False
        if not USE_GPIOZERO:
            GPIO.cleanup()
        sys.exit(0)

