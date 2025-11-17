#!/usr/bin/env python3
"""
Helper script to find the correct GPIO pins and SPI configuration for the ePaper display.

This script helps identify which pins are actually used by checking:
1. What SPI devices are available
2. What GPIO pins might be in use
3. Compare with known working configurations
"""

import os
import subprocess
import sys

def check_spi_devices():
    """Check available SPI devices."""
    print("=== SPI Devices ===")
    spi_devices = []
    for bus in range(2):
        for device in range(2):
            dev_path = f"/dev/spidev{bus}.{device}"
            if os.path.exists(dev_path):
                spi_devices.append((bus, device))
                print(f"  Found: {dev_path} (bus={bus}, device={device})")
    
    if not spi_devices:
        print("  No SPI devices found!")
    return spi_devices

def check_gpio_pins():
    """Check GPIO pin configuration."""
    print("\n=== GPIO Pin Information ===")
    print("Note: GPIO pins are BCM (Broadcom) pin numbers, not physical pin numbers")
    print("\nCommon ePaper pin configurations:")
    print("  Waveshare default: RST=17, DC=25, CS=8, BUSY=24, PWR=18")
    print("  SPI pins: MOSI=10, SCLK=11")
    print("\nTo find your pins:")
    print("  1. Check hardware documentation/schematic")
    print("  2. Check if epaperDriver.so source code is available")
    print("  3. Use GPIO tools to probe pins")
    
def print_usage():
    """Print usage instructions."""
    print("\n=== Configuration ===")
    print("Set environment variables to override default pins:")
    print("  export EPAPER_RST_PIN=17")
    print("  export EPAPER_DC_PIN=25")
    print("  export EPAPER_CS_PIN=8")
    print("  export EPAPER_BUSY_PIN=24")
    print("  export EPAPER_PWR_PIN=18")
    print("  export EPAPER_SPI_BUS=0")
    print("  export EPAPER_SPI_DEVICE=0")
    print("\nThen run your epaper demo:")
    print("  python epaper_demo.py")

def main():
    print("ePaper Pin Configuration Helper")
    print("=" * 50)
    
    check_spi_devices()
    check_gpio_pins()
    print_usage()
    
    print("\n=== Current Configuration ===")
    print(f"  EPAPER_RST_PIN={os.environ.get('EPAPER_RST_PIN', '17 (default)')}")
    print(f"  EPAPER_DC_PIN={os.environ.get('EPAPER_DC_PIN', '25 (default)')}")
    print(f"  EPAPER_CS_PIN={os.environ.get('EPAPER_CS_PIN', '8 (default)')}")
    print(f"  EPAPER_BUSY_PIN={os.environ.get('EPAPER_BUSY_PIN', '24 (default)')}")
    print(f"  EPAPER_PWR_PIN={os.environ.get('EPAPER_PWR_PIN', '18 (default)')}")
    print(f"  EPAPER_SPI_BUS={os.environ.get('EPAPER_SPI_BUS', '0 (default)')}")
    print(f"  EPAPER_SPI_DEVICE={os.environ.get('EPAPER_SPI_DEVICE', '0 (default)')}")

if __name__ == "__main__":
    main()

