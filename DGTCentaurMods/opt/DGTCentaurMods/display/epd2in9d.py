#!/usr/bin/python
# -*- coding:utf-8 -*-

"""
Waveshare 2.9-inch e-Paper Display Driver (EPD2IN9D)
Based on manufacturer specifications and standard e-paper display protocol
Resolution: 128x296 pixels
"""

from DGTCentaurMods.display import epdconfig
from DGTCentaurMods.board.logging import log
from PIL import Image

# Display resolution
EPD_WIDTH = 128
EPD_HEIGHT = 296


class EPD:
    def __init__(self):
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT

    def reset(self):
        """Hardware reset sequence per manufacturer specification"""
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(2)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)

    def send_command(self, command):
        """Send command byte to display"""
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([command])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data(self, data):
        """Send data byte to display"""
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([data])
        epdconfig.digital_write(self.cs_pin, 1)

    def ReadBusy(self):
        """Wait for display to become idle (busy pin LOW = idle, HIGH = busy)"""
        while epdconfig.digital_read(self.busy_pin) == 1:
            self.send_command(0x71)
            epdconfig.delay_ms(10)

    def TurnOnDisplay(self):
        """Turn on display and wait for completion"""
        self.send_command(0x12)
        epdconfig.delay_ms(10)
        self.ReadBusy()

    def init(self):
        """Initialize display per manufacturer specification"""
        if epdconfig.module_init() != 0:
            return -1
        
        # Hardware reset
        self.reset()
        
        # Power on and wait
        self.send_command(0x04)
        self.ReadBusy()
        
        # Panel setting - LUT from OTP
        self.send_command(0x00)
        self.send_data(0x1f)
        
        # Resolution setting
        self.send_command(0x61)
        self.send_data(0x80)
        self.send_data(0x01)
        self.send_data(0x28)
        
        # VCOM and data interval setting
        self.send_command(0x50)
        self.send_data(0x97)
        
        return 0

    def SetPartReg(self):
        """Set partial update register configuration"""
        # Power setting
        self.send_command(0x01)
        self.send_data(0x03)
        self.send_data(0x00)
        self.send_data(0x2b)
        self.send_data(0x2b)
        self.send_data(0x03)
        
        # Booster soft start
        self.send_command(0x06)
        self.send_data(0x17)
        self.send_data(0x17)
        self.send_data(0x17)
        
        # Power on
        self.send_command(0x04)
        self.ReadBusy()
        
        # Panel setting - 128x296
        self.send_command(0x00)
        self.send_data(0xbf)
        
        # PLL setting
        self.send_command(0x30)
        self.send_data(0x3a)
        
        # Resolution setting
        self.send_command(0x61)
        self.send_data(self.width)
        self.send_data((self.height >> 8) & 0xff)
        self.send_data(self.height & 0xff)
        
        # VCOM_DC setting
        self.send_command(0x82)
        self.send_data(0x12)
        
        # VCOM and data interval setting
        self.send_command(0x50)
        self.send_data(0x97)
        
        # LUT registers
        lut_vcom1 = [
            0x00, 0x19, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00,
        ]
        
        lut_ww1 = [
            0x00, 0x19, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        ]
        
        lut_bw1 = [
            0x80, 0x19, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        ]
        
        lut_wb1 = [
            0x40, 0x19, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        ]
        
        lut_bb1 = [
            0x00, 0x19, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        ]
        
        # Write LUT registers
        self.send_command(0x20)
        for count in range(0, 44):
            self.send_data(lut_vcom1[count])
        
        self.send_command(0x21)
        for count in range(0, 42):
            self.send_data(lut_ww1[count])
        
        self.send_command(0x22)
        for count in range(0, 42):
            self.send_data(lut_bw1[count])
        
        self.send_command(0x23)
        for count in range(0, 42):
            self.send_data(lut_wb1[count])
        
        self.send_command(0x24)
        for count in range(0, 42):
            self.send_data(lut_bb1[count])

    def getbuffer(self, image):
        """Convert PIL Image to display buffer format"""
        buf = [0xFF] * (int(self.width / 8) * self.height)
        image_monocolor = image.convert('1')
        imwidth, imheight = image_monocolor.size
        pixels = image_monocolor.load()
        
        if imwidth == self.width and imheight == self.height:
            # Vertical orientation (128x296)
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * self.width) / 8)] &= ~(0x80 >> (x % 8))
        elif imwidth == self.height and imheight == self.width:
            # Horizontal orientation (296x128)
            for y in range(imheight):
                for x in range(imwidth):
                    newx = y
                    newy = self.height - x - 1
                    if pixels[x, y] == 0:
                        buf[int((newx + newy * self.width) / 8)] &= ~(0x80 >> (y % 8))
        else:
            # Other size - map directly
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * self.width) / 8)] &= ~(0x80 >> (x % 8))
        
        return buf

    def display(self, image):
        """Full display update"""
        # Clear old data
        self.send_command(0x10)
        for i in range(0, int(self.width * self.height / 8)):
            self.send_data(0x00)
        epdconfig.delay_ms(10)
        
        # Send new image data
        self.send_command(0x13)
        for i in range(0, int(self.width * self.height / 8)):
            self.send_data(image[i])
        epdconfig.delay_ms(10)
        
        self.TurnOnDisplay()

    def DisplayPartial(self, image):
        """Partial display update"""
        self.SetPartReg()
        
        # Enter partial mode
        self.send_command(0x91)
        self.send_command(0x90)
        
        # Set partial window
        self.send_data(0)
        self.send_data(self.width - 1)
        self.send_data(0)
        self.send_data(0)
        self.send_data(int(self.height / 256))
        self.send_data(self.height % 256 - 1)
        self.send_data(0x28)
        
        # Send image data
        self.send_command(0x13)
        for i in range(0, int(self.width * self.height / 8)):
            self.send_data(image[i])
        epdconfig.delay_ms(10)
        
        self.TurnOnDisplay()

    def DisplayRegion(self, y0, y1, image):
        """Display specific region"""
        self.SetPartReg()
        
        # Enter partial mode
        self.send_command(0x91)
        self.send_command(0x90)
        
        # Set partial window
        self.send_data(0)
        self.send_data(self.width - 1)
        self.send_data(int(y0 / 256))
        self.send_data(y0 % 256)
        self.send_data(int(y1 / 256))
        self.send_data(y1 % 256 - 1)
        self.send_data(0x28)
        epdconfig.delay_ms(20)
        
        # Send image data
        self.send_command(0x13)
        for i in range(0, int(self.width * (y1 - y0) / 8)):
            self.send_data(image[i])
        
        self.TurnOnDisplay()

    def Clear(self, color):
        """Clear display to specified color (0xFF = white, 0x00 = black)"""
        # Clear old data
        self.send_command(0x10)
        for i in range(0, int(self.width * self.height / 8)):
            self.send_data(0x00)
        epdconfig.delay_ms(10)
        
        # Set new data
        self.send_command(0x13)
        for i in range(0, int(self.width * self.height / 8)):
            self.send_data(color)
        epdconfig.delay_ms(10)
        
        self.TurnOnDisplay()

    def sleep(self):
        """Enter deep sleep mode"""
        self.send_command(0x50)
        self.send_data(0xf7)
        self.send_command(0x02)
        self.send_command(0x07)
        self.send_data(0xA5)
        
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()
