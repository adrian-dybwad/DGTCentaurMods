"""
Hardware driver using Waveshare-style SPI communication.

Replaces epaperDriver.so with a pure Python implementation that communicates
directly with the UC8151 controller via SPI, following Waveshare's approach.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

try:
    import spidev
    import RPi.GPIO as GPIO
except ImportError:
    # For testing/development environments without hardware
    spidev = None
    GPIO = None

from PIL import Image

# Set up logging
logger = logging.getLogger(__name__)


# UC8151 Register Commands
UC8151_PSR = 0x00  # Panel Setting
UC8151_PWR = 0x01  # Power Setting
UC8151_POF = 0x02  # Power OFF
UC8151_PON = 0x04  # Power ON
UC8151_BTST = 0x06  # Booster Soft Start
UC8151_DSLP = 0x07  # Deep Sleep
UC8151_DTM1 = 0x10  # Data Start Transmission 1
UC8151_DSP = 0x11  # Data Stop
UC8151_DRF = 0x12  # Display Refresh
UC8151_PDTM1 = 0x14  # Partial Data Start Transmission 1
UC8151_PDTM2 = 0x15  # Partial Data Start Transmission 2
UC8151_PDRF = 0x16  # Partial Display Refresh
UC8151_LUT1 = 0x20  # LUT Register for VCOM
UC8151_LUTWW = 0x21  # LUT Register for White to White
UC8151_LUTBW = 0x22  # LUT Register for Black to White
UC8151_LUTWB = 0x23  # LUT Register for White to Black
UC8151_LUTBB = 0x24  # LUT Register for Black to Black
UC8151_PLL = 0x30  # PLL Control
UC8151_TSC = 0x40  # Temperature Sensor Control
UC8151_TSE = 0x41  # Temperature Sensor Enable
UC8151_TSW = 0x42  # Temperature Sensor Write
UC8151_TSR = 0x43  # Temperature Sensor Read
UC8151_CDI = 0x50  # VCOM and Data Interval Setting
UC8151_TCON = 0x60  # TCON Setting
UC8151_TRES = 0x61  # Resolution Setting
UC8151_REV = 0x70  # Revision
UC8151_FLG = 0x71  # Get Status
UC8151_AMV = 0x80  # Auto Measure VCOM
UC8151_VV = 0x81  # Read VCOM Value
UC8151_VDCS = 0x82  # VCOM DC Setting
UC8151_PWS = 0xE3  # Power Saving

# GPIO pins (typical Waveshare configuration - adjust if needed)
RST_PIN = 17
DC_PIN = 25
CS_PIN = 8
BUSY_PIN = 24

# Display dimensions
EPD_WIDTH = 128
EPD_HEIGHT = 296


class Driver:
    """
    Waveshare-style driver for UC8151 ePaper display.
    
    Uses direct SPI communication instead of epaperDriver.so.
    Supports partial refreshes with x/y coordinates.
    """

    def __init__(self) -> None:
        """Initialize the driver."""
        logger.info("Initializing Waveshare driver...")
        if spidev is None or GPIO is None:
            raise ImportError(
                "spidev and RPi.GPIO are required. Install with: pip install spidev RPi.GPIO"
            )
        
        # Display dimensions
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
        
        # SPI and GPIO setup
        self._spi: Optional[spidev.SpiDev] = None
        self._gpio_initialized = False
        
        try:
            # Initialize GPIO
            logger.info(f"Setting up GPIO pins: RST={RST_PIN}, DC={DC_PIN}, CS={CS_PIN}, BUSY={BUSY_PIN}")
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(RST_PIN, GPIO.OUT)
            GPIO.setup(DC_PIN, GPIO.OUT)
            GPIO.setup(CS_PIN, GPIO.OUT)
            GPIO.setup(BUSY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Pull up for input
            self._gpio_initialized = True
            
            # Initialize SPI
            logger.info("Opening SPI device (bus 0, device 0)...")
            self._spi = spidev.SpiDev()
            self._spi.open(0, 0)  # SPI bus 0, device 0
            self._spi.max_speed_hz = 4000000  # 4MHz
            self._spi.mode = 0b00
            logger.info("SPI initialized successfully")
            
            # Set initial pin states
            GPIO.output(CS_PIN, GPIO.HIGH)
            GPIO.output(DC_PIN, GPIO.LOW)
            GPIO.output(RST_PIN, GPIO.HIGH)
            logger.info("Driver initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize driver: {e}", exc_info=True)
            raise

    def _write_command(self, cmd: int) -> None:
        """Write a command byte to the display."""
        GPIO.output(DC_PIN, GPIO.LOW)  # Command mode
        GPIO.output(CS_PIN, GPIO.LOW)
        self._spi.xfer2([cmd])
        GPIO.output(CS_PIN, GPIO.HIGH)

    def _write_data(self, data: bytes | list[int]) -> None:
        """Write data bytes to the display."""
        GPIO.output(DC_PIN, GPIO.HIGH)  # Data mode
        GPIO.output(CS_PIN, GPIO.LOW)
        if isinstance(data, bytes):
            self._spi.xfer2(list(data))
        else:
            self._spi.xfer2(data)
        GPIO.output(CS_PIN, GPIO.HIGH)

    def _wait_until_idle(self) -> None:
        """
        Wait until the display is not busy.
        
        BUSY pin is LOW when busy, HIGH when idle (active low).
        """
        timeout = 5.0  # 5 second timeout
        start_time = time.time()
        while GPIO.input(BUSY_PIN) == GPIO.LOW:
            if time.time() - start_time > timeout:
                logger.warning("Timeout waiting for display to become idle")
                break
            time.sleep(0.01)

    def _convert_to_bytes(self, image: Image.Image) -> bytes:
        """
        Convert PIL Image to byte buffer format.
        
        The display expects a 1-bit monochrome bitmap in row-major order,
        with each byte containing 8 pixels (MSB first, left to right).
        """
        width, height = image.size
        bytes_per_row = (width + 7) // 8  # Round up to nearest byte
        buf = [0xFF] * (bytes_per_row * height)
        mono = image.convert("1")
        pixels = mono.load()
        
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:  # Black pixel
                    byte_index = y * bytes_per_row + (x // 8)
                    bit_position = x % 8
                    # MSB first: bit 0 (leftmost) is at position 7
                    buf[byte_index] &= ~(0x80 >> bit_position)
        
        return bytes(buf)

    def init(self) -> None:
        """Initialize the display hardware."""
        logger.info("Initializing display hardware...")
        try:
            # Reset
            logger.debug("Resetting display...")
            GPIO.output(RST_PIN, GPIO.LOW)
            time.sleep(0.01)
            GPIO.output(RST_PIN, GPIO.HIGH)
            time.sleep(0.01)
            
            # Power on sequence
            logger.debug("Powering on display...")
            self._write_command(UC8151_PON)
            self._wait_until_idle()
            
            # Panel setting
            self._write_command(UC8151_PSR)
            self._write_data([0xBF, 0x0D])  # LUT from OTP, scan up
            
            # Power setting
            self._write_command(UC8151_PWR)
            self._write_data([0x03, 0x00, 0x2B, 0x2B, 0x09])
            
            # Booster soft start
            self._write_command(UC8151_BTST)
            self._write_data([0x17, 0x17, 0x17])
            
            # Power off sequence (to prepare for first display)
            self._write_command(UC8151_POF)
            self._wait_until_idle()
            
            # PLL control
            self._write_command(UC8151_PLL)
            self._write_data([0x3C])  # 50Hz
            
            # Temperature sensor
            self._write_command(UC8151_TSE)
            self._write_data([0x00])
            
            # Resolution setting
            self._write_command(UC8151_TRES)
            self._write_data([
                (EPD_WIDTH >> 8) & 0xFF,
                EPD_WIDTH & 0xFF,
                (EPD_HEIGHT >> 8) & 0xFF,
                EPD_HEIGHT & 0xFF
            ])
            
            # VCOM and data interval
            self._write_command(UC8151_CDI)
            self._write_data([0x97])  # Border floating
            
            # Power on
            self._write_command(UC8151_PON)
            self._wait_until_idle()
            logger.info("Display initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize display: {e}", exc_info=True)
            raise

    def reset(self) -> None:
        """Reset the display hardware."""
        GPIO.output(RST_PIN, GPIO.LOW)
        time.sleep(0.01)
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.01)

    def full_refresh(self, image: Image.Image) -> None:
        """
        Perform a full screen refresh.
        
        Blocks until the hardware refresh completes.
        Typical duration is 1.5-2.0 seconds.
        """
        logger.debug("Starting full refresh...")
        try:
            # Rotate 180 degrees to match hardware orientation
            rotated = image.transpose(Image.ROTATE_180)
            image_bytes = self._convert_to_bytes(rotated)
            logger.debug(f"Image converted to bytes: {len(image_bytes)} bytes")
            
            # Power on
            self._write_command(UC8151_PON)
            self._wait_until_idle()
            
            # Send image data
            logger.debug("Sending image data...")
            self._write_command(UC8151_DTM1)
            self._write_data(image_bytes)
            
            # Display refresh
            logger.debug("Triggering display refresh...")
            self._write_command(UC8151_DRF)
            self._wait_until_idle()
            
            # Power off
            self._write_command(UC8151_POF)
            self._wait_until_idle()
            logger.debug("Full refresh complete")
        except Exception as e:
            logger.error(f"Full refresh failed: {e}", exc_info=True)
            raise

    def partial_refresh(self, x: int, y: int, width: int, height: int, image: Image.Image) -> None:
        """
        Perform a partial screen refresh with x/y coordinates.
        
        Args:
            x: X coordinate (left edge) of the region to refresh
            y: Y coordinate (top edge) of the region to refresh
            width: Width of the region to refresh
            height: Height of the region to refresh
            image: Image to display (should match the region size)
        
        Blocks until the hardware refresh completes.
        Typical duration is 260-300ms.
        """
        # Rotate 180 degrees to match hardware orientation
        rotated = image.transpose(Image.ROTATE_180)
        image_bytes = self._convert_to_bytes(rotated)
        
        # Convert coordinates to hardware orientation (rotated 180)
        # Hardware coordinates are from bottom-left, so we need to flip
        hw_x1 = self.width - x - width
        hw_y1 = self.height - y - height
        hw_x2 = self.width - x - 1
        hw_y2 = self.height - y - 1
        
        # Power on
        self._write_command(UC8151_PON)
        self._wait_until_idle()
        
        # Set partial window (PDTM1 sets the window boundaries)
        self._write_command(UC8151_PDTM1)
        # Send window coordinates: XSTART, XEND, YSTART, YEND
        self._write_data([
            (hw_x1 >> 8) & 0xFF,
            hw_x1 & 0xFF,
            (hw_x2 >> 8) & 0xFF,
            hw_x2 & 0xFF,
            (hw_y1 >> 8) & 0xFF,
            hw_y1 & 0xFF,
            (hw_y2 >> 8) & 0xFF,
            hw_y2 & 0xFF,
            0x01  # Gates scan both inside and outside of the partial window
        ])
        
        # Send image data (PDTM2 sends the actual image data)
        self._write_command(UC8151_PDTM2)
        self._write_data(image_bytes)
        
        # Partial display refresh
        self._write_command(UC8151_PDRF)
        self._wait_until_idle()
        
        # Power off
        self._write_command(UC8151_POF)
        self._wait_until_idle()

    def sleep(self) -> None:
        """Put the display into sleep mode."""
        self._write_command(UC8151_DSLP)
        self._write_data([0xA5])  # Deep sleep command
        self._wait_until_idle()

    def shutdown(self) -> None:
        """Power off the display and cleanup resources."""
        try:
            self._write_command(UC8151_POF)
            self._wait_until_idle()
            self.sleep()
        except Exception:
            pass  # Ignore errors during shutdown
        
        # Cleanup SPI
        if self._spi is not None:
            try:
                self._spi.close()
            except Exception:
                pass
            self._spi = None
        
        # Cleanup GPIO
        if self._gpio_initialized:
            try:
                GPIO.cleanup([RST_PIN, DC_PIN, CS_PIN, BUSY_PIN])
            except Exception:
                pass
            self._gpio_initialized = False
