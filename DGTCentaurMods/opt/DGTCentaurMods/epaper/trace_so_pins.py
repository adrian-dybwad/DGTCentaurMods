#!/usr/bin/env python3
"""
Trace the original epaperDriver.so to see what GPIO pins it actually uses.
This uses strace to monitor system calls and GPIO operations.
"""

import subprocess
import sys
from pathlib import Path

def find_so_file():
    """Find the epaperDriver.so file."""
    locations = [
        Path("/opt/DGTCentaurMods/display/epaperDriver.so"),
        Path("/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/display/epaperDriver.so"),
        Path(__file__).parent.parent / "display" / "epaperDriver.so",
    ]
    
    for loc in locations:
        if loc.exists():
            return loc
    return None

def trace_with_strace(so_path):
    """Use strace to trace GPIO operations."""
    print("=" * 60)
    print("TRACING GPIO OPERATIONS WITH STRACE")
    print("=" * 60)
    print(f"Tracing: {so_path}\n")
    
    # Create a test script that initializes the driver
    test_script = f"""
from ctypes import CDLL
import time

dll = CDLL('{so_path}')
print("Opening display...")
dll.openDisplay()
print("Initializing display...")
dll.init()
print("Waiting 2 seconds...")
time.sleep(2)
print("Closing display...")
dll.closeDisplay()
print("Done!")
"""
    
    # Write test script to temp file
    test_file = Path("/tmp/trace_epaper_test.py")
    test_file.write_text(test_script)
    
    print("Running strace to trace GPIO operations...")
    print("(This will show /dev/gpiochip* access and ioctl calls)\n")
    
    try:
        # Trace openat (for /dev/gpiochip*), ioctl (for GPIO operations), and write (for SPI)
        result = subprocess.run(
            [
                "strace",
                "-e", "trace=openat,ioctl,write",
                "-s", "200",  # Show more of strings
                "python3", str(test_file)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        print("STDOUT:")
        print(result.stdout)
        print("\nSTDERR (strace output):")
        print(result.stderr)
        
        # Extract GPIO-related lines
        print("\n" + "=" * 60)
        print("GPIO-RELATED OPERATIONS:")
        print("=" * 60)
        gpio_lines = []
        for line in result.stderr.split('\n'):
            if 'gpio' in line.lower() or 'ioctl' in line.lower():
                gpio_lines.append(line)
                print(line)
        
        if not gpio_lines:
            print("No GPIO operations found in trace.")
            print("The driver may use direct memory-mapped GPIO (BCM2835 style).")
        
    except FileNotFoundError:
        print("ERROR: strace not found. Install with: sudo apt-get install strace")
        return False
    except subprocess.TimeoutExpired:
        print("ERROR: Trace timed out after 30 seconds")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    
    return True

def trace_with_gpiod(so_path):
    """Try to monitor GPIO using libgpiod tools."""
    print("\n" + "=" * 60)
    print("MONITORING GPIO WITH LIBGPIOD")
    print("=" * 60)
    
    # Check if gpiod tools are available
    try:
        subprocess.run(["gpiodetect"], check=True, capture_output=True)
        print("gpiodetect available - checking GPIO chips...")
        result = subprocess.run(["gpiodetect"], capture_output=True, text=True)
        print(result.stdout)
    except FileNotFoundError:
        print("gpiodetect not found. Install with: sudo apt-get install gpiod")
        return False
    except subprocess.CalledProcessError:
        print("gpiodetect failed")
        return False
    
    return True

def check_gpio_debugfs():
    """Check /sys/kernel/debug/gpio if available."""
    print("\n" + "=" * 60)
    print("CHECKING GPIO DEBUGFS")
    print("=" * 60)
    
    debug_gpio = Path("/sys/kernel/debug/gpio")
    if debug_gpio.exists():
        print("Reading /sys/kernel/debug/gpio...")
        try:
            content = debug_gpio.read_text()
            print(content)
        except Exception as e:
            print(f"ERROR reading debugfs: {e}")
    else:
        print("/sys/kernel/debug/gpio not available")
        print("Enable with: sudo mount -t debugfs none /sys/kernel/debug")
    
    return True

def main():
    so_path = find_so_file()
    if not so_path:
        print("ERROR: Could not find epaperDriver.so")
        sys.exit(1)
    
    print(f"Found epaperDriver.so at: {so_path}\n")
    
    # Try multiple tracing methods
    trace_with_strace(so_path)
    trace_with_gpiod(so_path)
    check_gpio_debugfs()
    
    print("\n" + "=" * 60)
    print("ANALYSIS TIPS")
    print("=" * 60)
    print("""
Look for:
1. /dev/gpiochip* files being opened (indicates which GPIO chip)
2. ioctl calls with GPIO operations
3. Pin numbers in the ioctl parameters

Common GPIO operations:
- GPIO_GET_LINEINFO_IOCTL: Get line info (shows pin number)
- GPIOHANDLE_GET_LINE_VALUES_IOCTL: Read pin value
- GPIOHANDLE_SET_LINE_VALUES_IOCTL: Write pin value

If using BCM2835-style direct memory mapping, you may see:
- /dev/mem being opened
- mmap operations
- Direct memory writes to GPIO registers
""")

if __name__ == "__main__":
    main()

