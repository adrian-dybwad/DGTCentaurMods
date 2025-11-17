#!/usr/bin/env python3
"""
Test script to help identify correct GPIO pins for ePaper display.

This script tests GPIO pin access and SPI communication to help identify
the correct pin configuration.
"""

import os
import sys

def test_gpio_pin(pin_num):
    """Test if a GPIO pin can be accessed."""
    try:
        import gpiozero
        led = gpiozero.LED(pin_num)
        led.on()
        led.off()
        led.close()
        return True
    except Exception as e:
        print(f"  Pin {pin_num}: FAILED - {e}")
        return False

def test_spi(bus, device):
    """Test if SPI bus/device can be opened."""
    try:
        import spidev
        spi = spidev.SpiDev()
        spi.open(bus, device)
        spi.close()
        return True
    except Exception as e:
        print(f"  SPI bus={bus}, device={device}: FAILED - {e}")
        return False

def main():
    print("ePaper Pin Configuration Tester")
    print("=" * 50)
    
    # Check current environment variables
    print("\n=== Current Environment Configuration ===")
    pins = {
        'RST_PIN': os.environ.get('EPAPER_RST_PIN', '17'),
        'DC_PIN': os.environ.get('EPAPER_DC_PIN', '25'),
        'CS_PIN': os.environ.get('EPAPER_CS_PIN', '8'),
        'BUSY_PIN': os.environ.get('EPAPER_BUSY_PIN', '24'),
        'PWR_PIN': os.environ.get('EPAPER_PWR_PIN', '18'),
    }
    spi_bus = os.environ.get('EPAPER_SPI_BUS', '0')
    spi_device = os.environ.get('EPAPER_SPI_DEVICE', '0')
    
    for name, pin in pins.items():
        print(f"  {name}={pin}")
    print(f"  SPI_BUS={spi_bus}, SPI_DEVICE={spi_device}")
    
    # Test GPIO pins
    print("\n=== Testing GPIO Pins ===")
    print("Note: Some pins may fail if already in use or require root permissions")
    for name, pin in pins.items():
        pin_num = int(pin)
        print(f"Testing {name} (pin {pin_num})...", end=" ")
        if test_gpio_pin(pin_num):
            print("OK")
        else:
            print("FAILED")
    
    # Test SPI
    print(f"\n=== Testing SPI ===")
    print(f"Testing SPI bus={spi_bus}, device={spi_device}...", end=" ")
    if test_spi(int(spi_bus), int(spi_device)):
        print("OK")
    else:
        print("FAILED")
        print("\nTrying alternative SPI devices...")
        for bus in range(2):
            for device in range(2):
                if bus == int(spi_bus) and device == int(spi_device):
                    continue
                print(f"  Testing SPI bus={bus}, device={device}...", end=" ")
                if test_spi(bus, device):
                    print(f"OK - Try: export EPAPER_SPI_BUS={bus} EPAPER_SPI_DEVICE={device}")
                else:
                    print("FAILED")
    
    print("\n=== Instructions ===")
    print("If pins fail, try setting environment variables:")
    print("  export EPAPER_RST_PIN=<pin>")
    print("  export EPAPER_DC_PIN=<pin>")
    print("  export EPAPER_CS_PIN=<pin>")
    print("  export EPAPER_BUSY_PIN=<pin>")
    print("  export EPAPER_PWR_PIN=<pin>")
    print("  export EPAPER_SPI_BUS=<bus>")
    print("  export EPAPER_SPI_DEVICE=<device>")
    print("\nThen run: python epaper_demo.py")

if __name__ == "__main__":
    main()

