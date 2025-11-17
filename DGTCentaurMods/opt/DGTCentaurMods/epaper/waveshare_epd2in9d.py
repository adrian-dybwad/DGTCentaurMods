#!/usr/bin/python
# -*- coding:utf-8 -*-

import logging
from . import waveshare_epdconfig as epdconfig
from PIL import Image

EPD_WIDTH = 128
EPD_HEIGHT = 296

logger = logging.getLogger(__name__)


class EPD:
    def __init__(self):
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
    
    def reset(self):
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20) 
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(5)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)   
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(5)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)  
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(5)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(20)  

    def send_command(self, command):
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte(command)
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte(data)
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data2(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte2(data)
        epdconfig.digital_write(self.cs_pin, 1)
        
    def ReadBusy(self, timeout=5.0):
        """
        Wait for display to become idle.
        For DGT Centaur: BUSY pin is inverted (HIGH=busy, LOW=idle).
        """
        import time
        start = time.time()
        # Wait while pin reads HIGH (busy) - inverted logic for DGT Centaur
        while epdconfig.digital_read(self.busy_pin) == 1:
            if time.time() - start > timeout:
                logger.warning(f"e-Paper busy timeout after {timeout}s - pin still reads HIGH (busy)")
                return
            self.send_command(0x71)
            epdconfig.delay_ms(10)
        
    def TurnOnDisplay(self):
        self.send_command(0x12)
        epdconfig.delay_ms(10)
        self.ReadBusy()
        
    def init(self):
        if epdconfig.module_init() != 0:
            return -1
        self.reset()
        self.send_command(0x04)
        self.ReadBusy()
        self.send_command(0x00)
        self.send_data(0x1f)
        self.send_command(0x61)
        self.send_data(0x80)
        self.send_data(0x01)
        self.send_data(0x28)
        self.send_command(0X50)
        self.send_data(0x97)
        return 0
    
    def SetPartReg(self):
        self.send_command(0x01)
        self.send_data(0x03)
        self.send_data(0x00)
        self.send_data(0x2b)
        self.send_data(0x2b)
        self.send_data(0x03)
        self.send_command(0x06)
        self.send_data(0x17)
        self.send_data(0x17)
        self.send_data(0x17)
        self.send_command(0x04)
        self.ReadBusy()
        self.send_command(0x00)
        self.send_data(0xbf)
        self.send_command(0x30)
        self.send_data(0x3a)
        self.send_command(0x61)
        self.send_data(self.width)
        self.send_data((self.height >> 8) & 0xff)
        self.send_data(self.height & 0xff)
        self.send_command(0x82)
        self.send_data(0x12)
        self.send_command(0X50)
        self.send_data(0x97)

    def getbuffer(self, image):
        buf = [0xFF] * (int(self.width/8) * self.height)
        image_monocolor = image.convert('1')
        imwidth, imheight = image_monocolor.size
        pixels = image_monocolor.load()
        if imwidth == self.width and imheight == self.height:
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0:
                        buf[int((x + y * self.width) / 8)] &= ~(0x80 >> (x % 8))
        elif imwidth == self.height and imheight == self.width:
            for y in range(imheight):
                for x in range(imwidth):
                    newx = y
                    newy = self.height - x - 1
                    if pixels[x, y] == 0:
                        buf[int((newx + newy*self.width) / 8)] &= ~(0x80 >> (y % 8))
        return buf

    def display(self, image):
        self.send_command(0x10)
        self.send_data2([0x00] * int(self.width * self.height / 8))
        epdconfig.delay_ms(10)
        self.send_command(0x13)
        self.send_data2(image)
        epdconfig.delay_ms(10)
        self.TurnOnDisplay()
        
    def DisplayPartial(self, image):
        self.SetPartReg()
        self.send_command(0x91)
        self.send_command(0x90)
        self.send_data(0)
        self.send_data(self.width - 1)
        self.send_data(0)
        self.send_data(0)
        self.send_data(int(self.height / 256))
        self.send_data(self.height % 256 - 1)
        self.send_data(0x28)
        
        buf = [0x00] * int(self.width * self.height / 8)
        for i in range(0, int(self.width * self.height / 8)):
            buf[i] = ~image[i] & 0xFF
        self.send_command(0x10)
        self.send_data2(image)
        epdconfig.delay_ms(10)
        self.send_command(0x13)
        self.send_data2(buf)
        epdconfig.delay_ms(10)
        self.TurnOnDisplay()
        
    def Clear(self):
        self.send_command(0x10)
        self.send_data2([0x00] * int(self.width * self.height / 8))
        epdconfig.delay_ms(10)
        self.send_command(0x13)
        self.send_data2([0xFF] * int(self.width * self.height / 8))
        epdconfig.delay_ms(10)
        self.TurnOnDisplay()

    def sleep(self):
        self.send_command(0X50)
        self.send_data(0xf7)
        self.send_command(0X02)
        self.send_command(0X07)
        self.send_data(0xA5)
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()
