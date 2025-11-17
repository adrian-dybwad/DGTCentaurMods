#!/usr/bin/env python3
"""
Extract pin configuration from epaperDriver.so using various methods.
"""

import subprocess
import re
import sys
from pathlib import Path

def find_so_file():
    """Find the epaperDriver.so file."""
    # Try common locations
    locations = [
        Path(__file__).parent.parent / "display" / "epaperDriver.so",
        Path("/opt/DGTCentaurMods/display/epaperDriver.so"),
        Path("/home/pi/DGTCentaurMods/DGTCentaurMods/opt/DGTCentaurMods/display/epaperDriver.so"),
    ]
    
    for loc in locations:
        if loc.exists():
            return loc
    
    # Search in current directory
    for path in Path(".").rglob("epaperDriver.so"):
        return path
    
    return None

def extract_strings(so_path):
    """Extract strings from the .so file."""
    print("=" * 60)
    print("EXTRACTING STRINGS FROM .so FILE")
    print("=" * 60)
    try:
        result = subprocess.run(
            ["strings", str(so_path)],
            capture_output=True,
            text=True,
            check=True
        )
        strings = result.stdout
        
        # Look for pin-related strings
        pin_patterns = [
            r'pin\s*=\s*(\d+)',
            r'PIN\s*=\s*(\d+)',
            r'gpio\s*(\d+)',
            r'GPIO\s*(\d+)',
            r'RST[_\s]*(\d+)',
            r'DC[_\s]*(\d+)',
            r'CS[_\s]*(\d+)',
            r'BUSY[_\s]*(\d+)',
            r'PWR[_\s]*(\d+)',
            r'MOSI[_\s]*(\d+)',
            r'SCLK[_\s]*(\d+)',
            r'SPI[_\s]*(\d+)',
        ]
        
        print("\nLooking for pin numbers in strings...")
        found_pins = set()
        for line in strings.split('\n'):
            for pattern in pin_patterns:
                matches = re.findall(pattern, line, re.IGNORECASE)
                for match in matches:
                    pin_num = int(match)
                    if 0 <= pin_num <= 40:  # Valid GPIO pin range
                        found_pins.add(pin_num)
                        print(f"  Found potential pin: {pin_num} in: {line[:80]}")
        
        if found_pins:
            print(f"\nUnique pin numbers found: {sorted(found_pins)}")
        else:
            print("  No pin numbers found in strings")
        
        # Look for common pin values
        print("\nLooking for common pin numbers (12, 13, 16, 18, 24, 25)...")
        common_pins = [12, 13, 16, 18, 24, 25]
        for pin in common_pins:
            if str(pin) in strings:
                print(f"  Pin {pin} appears in strings")
        
        return strings
    except FileNotFoundError:
        print("ERROR: 'strings' command not found. Install binutils.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"ERROR running strings: {e}")
        return None

def extract_symbols(so_path):
    """Extract symbols from the .so file."""
    print("\n" + "=" * 60)
    print("EXTRACTING SYMBOLS FROM .so FILE")
    print("=" * 60)
    try:
        result = subprocess.run(
            ["nm", "-D", str(so_path)],
            capture_output=True,
            text=True,
            check=True
        )
        symbols = result.stdout
        
        print("\nFunction symbols:")
        for line in symbols.split('\n'):
            if ' T ' in line or ' t ' in line:  # Text (code) symbols
                print(f"  {line}")
        
        print("\nData symbols (may contain pin constants):")
        for line in symbols.split('\n'):
            if ' D ' in line or ' d ' in line or ' B ' in line or ' b ' in line:  # Data/bss symbols
                print(f"  {line}")
        
        return symbols
    except FileNotFoundError:
        print("ERROR: 'nm' command not found. Install binutils.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"ERROR running nm: {e}")
        return None

def extract_objdump(so_path):
    """Extract disassembly and constants from .so file."""
    print("\n" + "=" * 60)
    print("EXTRACTING DISASSEMBLY FROM .so FILE")
    print("=" * 60)
    try:
        # Get disassembly
        result = subprocess.run(
            ["objdump", "-d", str(so_path)],
            capture_output=True,
            text=True,
            check=True
        )
        disasm = result.stdout
        
        # Look for immediate values that might be pin numbers
        print("\nLooking for immediate values that might be pin numbers...")
        pin_values = [12, 13, 16, 18, 24, 25]
        for pin in pin_values:
            # Look for mov, movw, or similar instructions with immediate values
            pattern = rf'\b{pin}\b'
            matches = re.findall(pattern, disasm)
            if matches:
                print(f"  Found {pin} in disassembly ({len(matches)} times)")
                # Show context
                lines = disasm.split('\n')
                for i, line in enumerate(lines):
                    if str(pin) in line and ('mov' in line.lower() or 'ldr' in line.lower()):
                        print(f"    {line[:100]}")
                        if i < len(lines) - 1:
                            print(f"    {lines[i+1][:100]}")
                        break
        
        return disasm
    except FileNotFoundError:
        print("ERROR: 'objdump' command not found. Install binutils.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"ERROR running objdump: {e}")
        return None

def trace_runtime(so_path):
    """Suggest using strace/ltrace to trace runtime behavior."""
    print("\n" + "=" * 60)
    print("RUNTIME TRACING SUGGESTIONS")
    print("=" * 60)
    print("""
To see what pins the .so driver actually uses at runtime, you can:

1. Use strace to trace system calls:
   strace -e trace=openat,ioctl python3 -c "
   from ctypes import CDLL
   dll = CDLL('{}')
   dll.openDisplay()
   dll.init()
   "

2. Use ltrace to trace library calls:
   ltrace python3 -c "
   from ctypes import CDLL
   dll = CDLL('{}')
   dll.openDisplay()
   dll.init()
   "

3. Monitor GPIO access:
   # Before running the driver
   watch -n 0.1 'cat /sys/kernel/debug/gpio | grep -E "gpio-1[0-9]|gpio-2[0-9]"'

4. Check /dev/gpiochip* access:
   strace -e trace=openat python3 your_script.py 2>&1 | grep gpio
""".format(so_path, so_path))

def main():
    so_path = find_so_file()
    if not so_path:
        print("ERROR: Could not find epaperDriver.so")
        print("Searched in:")
        print("  - ./display/epaperDriver.so")
        print("  - /opt/DGTCentaurMods/display/epaperDriver.so")
        print("  - Current directory recursively")
        sys.exit(1)
    
    print(f"Found epaperDriver.so at: {so_path}")
    print(f"File size: {so_path.stat().st_size} bytes")
    
    # Extract information using multiple methods
    strings = extract_strings(so_path)
    symbols = extract_symbols(so_path)
    disasm = extract_objdump(so_path)
    trace_runtime(so_path)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
If pin numbers are not found in the binary, they may be:
1. Hardcoded in the source code (not in binary)
2. Configured via environment variables
3. Read from a config file
4. Set via function parameters

Try runtime tracing (strace/ltrace) to see actual pin usage.
""")

if __name__ == "__main__":
    main()

