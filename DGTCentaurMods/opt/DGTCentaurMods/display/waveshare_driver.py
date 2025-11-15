"""
Waveshare 2.9" e-paper display driver.

Refactored version with better encapsulation and cleaner interface.

This file is part of the DGTCentaur Mods open source software
( https://github.com/EdNekebno/DGTCentaur )

Original hardware driver by Waveshare team.
Refactored for DGTCentaur Mods.
"""

from typing import List
from PIL import Image
import time

from DGTCentaurMods.display import epdconfig
from DGTCentaurMods.display.display_types import DISPLAY_WIDTH, DISPLAY_HEIGHT
from DGTCentaurMods.board.logging import log


class WaveshareDriver:
    """
    Driver for Waveshare 2.9" e-paper display.
    
    Handles low-level SPI communication and display commands.
    """
    
    # Look-up tables for partial update waveforms
    _LUT_VCOM1 = [
        0x00, 0x19, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00,
    ]
    
    _LUT_WW1 = [
        0x00, 0x19, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    _LUT_BW1 = [
        0x80, 0x19, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    _LUT_WB1 = [
        0x40, 0x19, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    _LUT_BB1 = [
        0x00, 0x19, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    
    def __init__(self):
        """Initialize the Waveshare driver."""
        self.width = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT
        
        # Initialize GPIO configuration
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
    
    def reset(self) -> None:
        """Perform hardware reset sequence."""
        for _ in range(4):
            epdconfig.digital_write(self.reset_pin, 1)
            epdconfig.delay_ms(20)
            epdconfig.digital_write(self.reset_pin, 0)
            epdconfig.delay_ms(5)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)
    
    def send_command(self, command: int) -> None:
        """
        Send a command byte to the display.
        
        Args:
            command: Command byte
        """
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([command])
        epdconfig.digital_write(self.cs_pin, 1)
    
    def send_data(self, data: int) -> None:
        """
        Send a data byte to the display.
        
        Args:
            data: Data byte
        """
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([data])
        epdconfig.digital_write(self.cs_pin, 1)
    
    def wait_until_idle(self) -> None:
        """Wait for display to become idle (not currently used)."""
        pass
    
    def turn_on_display(self) -> None:
        """Turn on the display (refresh command)."""
        self.send_command(0x12)
        epdconfig.delay_ms(10)
        self.wait_until_idle()
    
    def init(self) -> int:
        """
        Initialize the display hardware.
        
        Returns:
            0 on success, -1 on failure
        """
        if epdconfig.module_init() != 0:
            return -1
        
        # Hardware init sequence
        self.reset()
        
        self.send_command(0x04)  # Power on
        self.wait_until_idle()
        
        self.send_command(0x00)  # Panel setting
        self.send_data(0x1f)     # LUT from OTP, KW-BF KWR-AF BWROTP 0f BWOTP 1f
        
        self.send_command(0x61)  # Resolution setting
        self.send_data(0x80)     # 128
        self.send_data(0x01)     # 296 high byte
        self.send_data(0x28)     # 296 low byte
        
        self.send_command(0x50)  # VCOM and data interval setting
        self.send_data(0x97)     # WBmode
        
        return 0
    
    def _set_partial_reg(self) -> None:
        """Configure registers for partial update mode."""
        self.send_command(0x01)  # Power setting
        self.send_data(0x03)
        self.send_data(0x00)
        self.send_data(0x2b)
        self.send_data(0x2b)
        self.send_data(0x03)
        
        self.send_command(0x06)  # Boost soft start
        self.send_data(0x17)
        self.send_data(0x17)
        self.send_data(0x17)
        
        self.send_command(0x04)  # Power on
        self.wait_until_idle()
        
        self.send_command(0x00)  # Panel setting
        self.send_data(0xbf)     # LUT from OTP, 128x296
        
        self.send_command(0x30)  # PLL setting
        self.send_data(0x3a)     # 100Hz
        
        self.send_command(0x61)  # Resolution setting
        self.send_data(self.width)
        self.send_data((self.height >> 8) & 0xff)
        self.send_data(self.height & 0xff)
        
        self.send_command(0x82)  # VCM_DC setting
        self.send_data(0x12)
        
        self.send_command(0x50)  # VCOM and data interval setting
        self.send_data(0x97)
        
        # Load LUTs
        self.send_command(0x20)  # VCOM
        for count in range(44):
            self.send_data(self._LUT_VCOM1[count])
        
        self.send_command(0x21)  # White to white
        for count in range(42):
            self.send_data(self._LUT_WW1[count])
        
        self.send_command(0x22)  # Black to white
        for count in range(42):
            self.send_data(self._LUT_BW1[count])
        
        self.send_command(0x23)  # White to black
        for count in range(42):
            self.send_data(self._LUT_WB1[count])
        
        self.send_command(0x24)  # Black to black
        for count in range(42):
            self.send_data(self._LUT_BB1[count])
    
    def get_buffer(self, image: Image.Image) -> List[int]:
        """
        Convert PIL Image to display buffer.
        
        Args:
            image: PIL Image in mode '1'
            
        Returns:
            List of bytes for display
        """
        buf = [0xFF] * (int(self.width / 8) * self.height)
        image_mono = image.convert('1')
        img_width, img_height = image_mono.size
        pixels = image_mono.load()
        
        if img_width == self.width and img_height == self.height:
            # Vertical orientation
            log.debug("Vertical orientation")
            for y in range(img_height):
                for x in range(img_width):
                    if pixels[x, y] == 0:
                        buf[int((x + y * self.width) / 8)] &= ~(0x80 >> (x % 8))
        
        elif img_width == self.height and img_height == self.width:
            # Horizontal orientation
            log.debug("Horizontal orientation")
            for y in range(img_height):
                for x in range(img_width):
                    new_x = y
                    new_y = self.height - x - 1
                    if pixels[x, y] == 0:
                        buf[int((new_x + new_y * self.width) / 8)] &= ~(0x80 >> (y % 8))
        
        else:
            # Other size
            log.debug("Other orientation")
            for y in range(min(img_height, self.height)):
                for x in range(min(img_width, self.width)):
                    if pixels[x, y] == 0:
                        buf[int((x + y * self.width) / 8)] &= ~(0x80 >> (x % 8))
        
        return buf
    
    def display(self, image: List[int]) -> None:
        """
        Display a full screen image.
        
        Args:
            image: Buffer to display
        """
        self.send_command(0x10)  # Write to black/white RAM
        for i in range(int(self.width * self.height / 8)):
            self.send_data(0x00)
        epdconfig.delay_ms(10)
        
        self.send_command(0x13)  # Write to red/black RAM
        for i in range(int(self.width * self.height / 8)):
            self.send_data(image[i])
        epdconfig.delay_ms(10)
        
        self.turn_on_display()
    
    def display_partial(self, image: Image.Image) -> None:
        """
        Display using partial refresh.
        
        Args:
            image: PIL Image to display
        """
        self._set_partial_reg()
        
        self.send_command(0x91)  # Enter partial mode
        self.send_command(0x90)  # Set resolution
        self.send_data(0)
        self.send_data(self.width - 1)
        self.send_data(0)
        self.send_data(0)
        self.send_data(int(self.height / 256))
        self.send_data(self.height % 256 - 1)
        self.send_data(0x28)
        
        self.send_command(0x13)  # Write to RAM
        buffer = self.get_buffer(image)
        for i in range(int(self.width * self.height / 8)):
            self.send_data(buffer[i])
        epdconfig.delay_ms(10)
        
        self.turn_on_display()
    
    def display_region(self, y0: int, y1: int, image: Image.Image) -> None:
        """
        Display a partial region.
        
        Args:
            y0: Start row
            y1: End row
            image: PIL Image to display in region
        """
        self._set_partial_reg()
        
        self.send_command(0x91)  # Enter partial mode
        self.send_command(0x90)  # Set resolution
        self.send_data(0)
        self.send_data(self.width - 1)
        self.send_data(int(y0 / 256))
        self.send_data(y0 % 256)
        self.send_data(int(y1 / 256))
        self.send_data(y1 % 256 - 1)
        self.send_data(0x28)
        epdconfig.delay_ms(20)
        
        self.send_command(0x13)  # Write to RAM
        buffer = self.get_buffer(image)
        for i in range(int(self.width * (y1 - y0) / 8)):
            self.send_data(buffer[i])
        
        self.turn_on_display()
    
    def clear(self, color: int = 0xFF) -> None:
        """
        Clear the display to a solid color.
        
        Args:
            color: Fill color (0x00 for black, 0xFF for white)
        """
        self.send_command(0x10)  # Write to black/white RAM
        for i in range(int(self.width * self.height / 8)):
            self.send_data(0x00)
        epdconfig.delay_ms(10)
        
        self.send_command(0x13)  # Write to red/black RAM
        for i in range(int(self.width * self.height / 8)):
            self.send_data(color)
        epdconfig.delay_ms(10)
        
        self.turn_on_display()
    
    def sleep(self) -> None:
        """Put display into deep sleep mode."""
        self.send_command(0x50)  # VCOM and data interval setting
        self.send_data(0xf7)
        
        self.send_command(0x02)  # Power off
        self.send_command(0x07)  # Deep sleep
        self.send_data(0xA5)
        
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()

