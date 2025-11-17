"""
Hardware driver using Waveshare-style SPI communication.

Replaces epaperDriver.so with a pure Python implementation that communicates
directly with the UC8151 controller via SPI, following Waveshare's approach.
"""

from __future__ import annotations

import logging
import os
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

# GPIO pins - configurable via environment variables
# Default values are typical Waveshare configuration for 2.9" display
# Note: CS_PIN=8 corresponds to SPI0 CE0 (hardware chip select)
# If using hardware CS, set EPAPER_USE_HW_CS=true to let SPI handle CS automatically
# IMPORTANT: When using hardware CS, the CS_PIN value is ignored - SPI hardware
# automatically uses CE0 (GPIO 8) for device 0, CE1 (GPIO 7) for device 1
# To find the correct pins used by epaperDriver.so, check:
# 1. Hardware documentation/schematics
# 2. Use GPIO probing tools on a working system
# 3. Check Waveshare epd2in9d.py source code
# 4. Try common configurations: (17,25,8,24) or (17,25,0,24) or (17,25,1,24)
RST_PIN = int(os.environ.get("EPAPER_RST_PIN", "17"))
DC_PIN = int(os.environ.get("EPAPER_DC_PIN", "25"))
CS_PIN = int(os.environ.get("EPAPER_CS_PIN", "8"))  # Only used if not using hardware CS
BUSY_PIN = int(os.environ.get("EPAPER_BUSY_PIN", "24"))
USE_HW_CS = os.environ.get("EPAPER_USE_HW_CS", "").lower() == "true"

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
            logger.info(f"Hardware CS mode: {USE_HW_CS} (if True, SPI handles CS automatically)")
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(RST_PIN, GPIO.OUT)
            GPIO.setup(DC_PIN, GPIO.OUT)
            if not USE_HW_CS:
                # Only setup CS as GPIO if not using hardware CS
                GPIO.setup(CS_PIN, GPIO.OUT)
            GPIO.setup(BUSY_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Pull up for input
            self._gpio_initialized = True
            
            # Initialize SPI
            # SPI bus and device configurable via environment variables
            spi_bus = int(os.environ.get("EPAPER_SPI_BUS", "0"))
            spi_device = int(os.environ.get("EPAPER_SPI_DEVICE", "0"))
            spi_speed = int(os.environ.get("EPAPER_SPI_SPEED", "4000000"))  # Default 4MHz
            spi_mode = int(os.environ.get("EPAPER_SPI_MODE", "0"))  # Default mode 0
            logger.info(f"Opening SPI device (bus {spi_bus}, device {spi_device})...")
            logger.info(f"SPI settings: speed={spi_speed}Hz, mode={spi_mode}")
            self._spi = spidev.SpiDev()
            self._spi.open(spi_bus, spi_device)
            self._spi.max_speed_hz = spi_speed
            self._spi.mode = spi_mode
            self._spi.lsbfirst = False  # MSB first
            self._spi.bits_per_word = 8
            logger.info("SPI initialized successfully")
            
            # Set initial pin states
            if not USE_HW_CS:
                GPIO.output(CS_PIN, GPIO.HIGH)
            GPIO.output(DC_PIN, GPIO.LOW)
            GPIO.output(RST_PIN, GPIO.HIGH)
            logger.info("Driver initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize driver: {e}", exc_info=True)
            raise

    def _write_command(self, cmd: int) -> None:
        """Write a command byte to the display."""
        logger.debug(f"Sending command: 0x{cmd:02X}")
        GPIO.output(DC_PIN, GPIO.LOW)  # Command mode
        if not USE_HW_CS:
            GPIO.output(CS_PIN, GPIO.LOW)
            time.sleep(0.0001)  # Small delay for CS to settle
        self._spi.xfer2([cmd])
        if not USE_HW_CS:
            time.sleep(0.0001)  # Small delay before raising CS
            GPIO.output(CS_PIN, GPIO.HIGH)
            time.sleep(0.0001)  # Small delay after CS

    def _write_data(self, data: bytes | list[int]) -> None:
        """
        Write data bytes to the display.
        
        Sends data in chunks to avoid SPI transfer size limits (4096 bytes max).
        """
        GPIO.output(DC_PIN, GPIO.HIGH)  # Data mode
        if not USE_HW_CS:
            GPIO.output(CS_PIN, GPIO.LOW)
            time.sleep(0.0001)  # Small delay for CS to settle
        
        # Convert to list if needed
        if isinstance(data, bytes):
            data_list = list(data)
        else:
            data_list = data
        
        # Send in chunks of 4096 bytes to avoid SPI transfer limit
        chunk_size = 4096
        for i in range(0, len(data_list), chunk_size):
            chunk = data_list[i:i + chunk_size]
            self._spi.xfer2(chunk)
        
        if not USE_HW_CS:
            time.sleep(0.0001)  # Small delay before raising CS
            GPIO.output(CS_PIN, GPIO.HIGH)
            time.sleep(0.0001)  # Small delay after CS

    def _wait_until_idle(self) -> None:
        """
        Wait until the display is not busy.
        
        BUSY pin logic can be inverted via EPAPER_BUSY_INVERTED env var.
        Default: LOW when busy, HIGH when idle (active low).
        If inverted: HIGH when busy, LOW when idle (active high).
        If BUSY pin is not working, can be disabled via EPAPER_SKIP_BUSY env var.
        """
        # Allow skipping BUSY wait if pin is not connected/working
        if os.environ.get("EPAPER_SKIP_BUSY", "").lower() == "true":
            logger.debug("Skipping BUSY pin wait (EPAPER_SKIP_BUSY=true)")
            time.sleep(0.1)  # Small delay instead
            return
        
        # Check if BUSY pin logic is inverted
        busy_inverted = os.environ.get("EPAPER_BUSY_INVERTED", "").lower() == "true"
        
        timeout = 5.0  # 5 second timeout
        start_time = time.time()
        initial_state = GPIO.input(BUSY_PIN)
        
        if busy_inverted:
            # Inverted: HIGH when busy, LOW when idle
            logger.debug(f"BUSY pin state: {initial_state} (inverted: 0=LOW/idle, 1=HIGH/busy)")
            if initial_state == GPIO.LOW:
                # Already idle
                logger.debug("Display already idle (BUSY pin LOW)")
                return
            # Wait for pin to go LOW (idle)
            while GPIO.input(BUSY_PIN) == GPIO.HIGH:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.warning(f"Timeout waiting for display to become idle after {elapsed:.2f}s")
                    logger.warning("If BUSY pin is not connected, set EPAPER_SKIP_BUSY=true")
                    break
                time.sleep(0.01)
        else:
            # Standard: LOW when busy, HIGH when idle
            logger.debug(f"BUSY pin state: {initial_state} (0=LOW/busy, 1=HIGH/idle)")
            if initial_state == GPIO.HIGH:
                # Already idle
                logger.debug("Display already idle (BUSY pin HIGH)")
                return
            # Wait for pin to go HIGH (idle)
            while GPIO.input(BUSY_PIN) == GPIO.LOW:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.warning(f"Timeout waiting for display to become idle after {elapsed:.2f}s")
                    logger.warning("If BUSY pin is not connected, set EPAPER_SKIP_BUSY=true")
                    logger.warning("If BUSY pin logic is inverted, set EPAPER_BUSY_INVERTED=true")
                    break
                time.sleep(0.01)
        
        elapsed = time.time() - start_time
        if elapsed > 0.01:
            logger.debug(f"Waited {elapsed:.2f}s for display to become idle")

    def _convert_to_bytes(self, image: Image.Image) -> bytes:
        """
        Convert PIL Image to byte buffer format.
        
        The display expects a 1-bit monochrome bitmap in row-major order,
        with each byte containing 8 pixels (MSB first, left to right).
        
        Note: The old epaperDriver.so used a different formula, but this one
        is correct for row-major order. If the display doesn't work, we may
        need to try the old formula or check if the display expects column-major.
        """
        width, height = image.size
        bytes_per_row = (width + 7) // 8  # Round up to nearest byte
        buf = [0xFF] * (bytes_per_row * height)
        mono = image.convert("1")
        pixels = mono.load()
        
        # Try old driver's formula if environment variable is set
        use_old_formula = os.environ.get("EPAPER_USE_OLD_FORMULA", "").lower() == "true"
        
        if use_old_formula:
            # Old epaperDriver.so formula (testing compatibility)
            # Uses: int((x + y * width) / 8) which should be equivalent to row-major
            # when width is a multiple of 8
            for y in range(height):
                for x in range(width):
                    if pixels[x, y] == 0:  # Black pixel
                        byte_index = int((x + y * width) / 8)
                        bit_position = x % 8
                        if byte_index < len(buf):  # Safety check
                            buf[byte_index] &= ~(0x80 >> bit_position)
        else:
            # Correct row-major formula
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
            # Reset - longer delay to ensure proper reset
            logger.debug("Resetting display...")
            GPIO.output(RST_PIN, GPIO.LOW)
            time.sleep(0.02)
            GPIO.output(RST_PIN, GPIO.HIGH)
            time.sleep(0.02)
            
            # Check BUSY pin state before starting
            busy_state = GPIO.input(BUSY_PIN)
            logger.info(f"BUSY pin initial state: {busy_state} (0=LOW, 1=HIGH)")
            
            # Panel setting (PSR) - must come first
            logger.debug("Setting panel configuration (PSR)...")
            self._write_command(UC8151_PSR)
            self._write_data([0xBF, 0x0D])  # LUT from OTP, scan up
            time.sleep(0.01)
            
            # Power setting (PWR)
            logger.debug("Setting power configuration (PWR)...")
            self._write_command(UC8151_PWR)
            self._write_data([0x03, 0x00, 0x2B, 0x2B, 0x09])
            time.sleep(0.01)
            
            # Booster soft start (BTST)
            logger.debug("Setting booster soft start (BTST)...")
            self._write_command(UC8151_BTST)
            self._write_data([0x17, 0x17, 0x17])
            time.sleep(0.01)
            
            # PLL control
            logger.debug("Setting PLL...")
            self._write_command(UC8151_PLL)
            self._write_data([0x3C])  # 50Hz
            time.sleep(0.01)
            
            # Temperature sensor
            logger.debug("Setting temperature sensor...")
            self._write_command(UC8151_TSE)
            self._write_data([0x00])
            time.sleep(0.01)
            
            # Resolution setting
            logger.debug(f"Setting resolution: {EPD_WIDTH}x{EPD_HEIGHT}...")
            self._write_command(UC8151_TRES)
            self._write_data([
                (EPD_WIDTH >> 8) & 0xFF,
                EPD_WIDTH & 0xFF,
                (EPD_HEIGHT >> 8) & 0xFF,
                EPD_HEIGHT & 0xFF
            ])
            time.sleep(0.01)
            
            # VCOM and data interval
            logger.debug("Setting VCOM and data interval...")
            self._write_command(UC8151_CDI)
            self._write_data([0x97])  # Border floating
            time.sleep(0.01)
            
            # Power on
            logger.debug("Powering on display (PON)...")
            self._write_command(UC8151_PON)
            # Wait for power to stabilize - don't use BUSY pin during init
            time.sleep(0.2)
            
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
        logger.info("Starting full refresh...")
        try:
            # Rotate 180 degrees to match hardware orientation
            rotated = image.transpose(Image.ROTATE_180)
            image_bytes = self._convert_to_bytes(rotated)
            logger.debug(f"Image converted to bytes: {len(image_bytes)} bytes (expected: {EPD_WIDTH * EPD_HEIGHT // 8})")
            
            # Verify image size
            expected_size = (EPD_WIDTH * EPD_HEIGHT) // 8
            if len(image_bytes) != expected_size:
                logger.warning(f"Image size mismatch: got {len(image_bytes)}, expected {expected_size}")
            
            # Power on
            logger.debug("Powering on for refresh...")
            self._write_command(UC8151_PON)
            if os.environ.get("EPAPER_SKIP_BUSY", "").lower() == "true":
                time.sleep(0.1)  # Small delay instead of BUSY wait
            else:
                self._wait_until_idle()
            
            # Send image data
            logger.debug("Sending image data...")
            self._write_command(UC8151_DTM1)
            self._write_data(image_bytes)
            logger.debug("Image data sent")
            
            # Display refresh
            logger.debug("Triggering display refresh...")
            refresh_start = time.time()
            self._write_command(UC8151_DRF)
            
            # Wait for refresh to complete
            # If BUSY pin is not working, use fixed delay based on UC8151 specs
            if os.environ.get("EPAPER_SKIP_BUSY", "").lower() == "true":
                # Full refresh takes 1.5-2.0 seconds per UC8151 datasheet
                logger.debug("Using fixed delay for full refresh (1.8s)...")
                time.sleep(1.8)
            else:
                self._wait_until_idle()
            
            refresh_duration = time.time() - refresh_start
            logger.info(f"Display refresh completed in {refresh_duration:.2f}s")
            
            if refresh_duration < 1.0:
                logger.warning(f"Refresh too fast ({refresh_duration:.2f}s) - display may not have updated!")
            
            # Power off
            logger.debug("Powering off...")
            self._write_command(UC8151_POF)
            if os.environ.get("EPAPER_SKIP_BUSY", "").lower() == "true":
                time.sleep(0.1)  # Small delay instead of BUSY wait
            else:
                self._wait_until_idle()
            logger.info("Full refresh complete")
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
                pins_to_cleanup = [RST_PIN, DC_PIN, BUSY_PIN]
                if not USE_HW_CS:
                    pins_to_cleanup.append(CS_PIN)
                GPIO.cleanup(pins_to_cleanup)
            except Exception:
                pass
            self._gpio_initialized = False
