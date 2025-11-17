#!/usr/bin/python
# -*- coding:utf-8 -*-

# *****************************************************************************
# * | File        :   epd2in9d.py
# * | Author      :   Waveshare team
# * | Function    :   Electronic paper driver
# * | Info        :
# *----------------
# * | This version:   V2.1
# * | Date        :   2022-08-10
# # | Info        :   python demo
# -----------------------------------------------------------------------------
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import logging
import os
from . import waveshare_epdconfig as epdconfig
from PIL import Image
try:
    import RPi.GPIO as GPIO
except ImportError:
    # GPIO not available (e.g., on non-Raspberry Pi systems)
    pass

# Display resolution
EPD_WIDTH       = 128
EPD_HEIGHT      = 296

logger = logging.getLogger(__name__)

class EPD:
    def __init__(self):
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
    
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
        
    # Hardware reset
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

    # send a lot of data   
    def send_data2(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte2(data)
        epdconfig.digital_write(self.cs_pin, 1)
        
    def ReadBusy(self):
        logger.debug("e-Paper busy")
        import time
        timeout = 5.0  # 5 second timeout
        start_time = time.time()
        
        # Check if BUSY logic is inverted via environment variable
        # Some hardware uses HIGH=busy, LOW=idle instead of the standard LOW=busy, HIGH=idle
        inverted_logic = os.environ.get("EPAPER_BUSY_INVERTED", "").lower() == "true"
        
        # Read initial state
        initial_state = epdconfig.digital_read(self.busy_pin)
        logger.debug(f"Initial BUSY pin state: {initial_state} (pin={self.busy_pin}, inverted={inverted_logic})")
        
        if inverted_logic:
            # Inverted logic: HIGH (1) = busy, LOW (0) = idle
            # Wait while pin is HIGH (1) = busy, exit when LOW (0) = idle
            if initial_state == 0:
                logger.debug("BUSY pin is LOW - already idle (inverted logic)")
                return
            
            check_count = 0
            while True:
                current_state = epdconfig.digital_read(self.busy_pin)
                elapsed = time.time() - start_time
                
                # Exit when pin goes LOW (0) = idle
                if current_state == 0:
                    logger.debug(f"e-Paper busy release (pin now LOW/idle) after {elapsed:.2f}s")
                    break
                
                # Check timeout
                if elapsed > timeout:
                    logger.warning(f"e-Paper busy timeout after {elapsed:.1f}s - pin still reads {current_state} (HIGH=busy, inverted)")
                    logger.warning(f"Pin {self.busy_pin} may be wrong or hardware not responding")
                    logger.warning("Continuing anyway - display may still work if SPI is functioning")
                    break
                
                # Send command to check status periodically
                if check_count % 10 == 0:  # Every 100ms
                    self.send_command(0x71)
                epdconfig.delay_ms(10)
                check_count += 1
        else:
            # Standard UC8151 logic: LOW (0) = busy, HIGH (1) = idle
            # With pull_up=True, floating pin reads HIGH (1), which is idle
            # So we wait while pin is LOW (0) = busy, exit when HIGH (1) = idle
            
            # If pin is already HIGH, it might be idle (or floating with pull-up)
            if initial_state == 1:
                logger.debug("BUSY pin is HIGH - may already be idle, waiting briefly to confirm...")
                epdconfig.delay_ms(50)
                new_state = epdconfig.digital_read(self.busy_pin)
                if new_state == 1:
                    logger.debug("BUSY pin still HIGH - assuming idle")
                    return
            
            # Wait while pin is LOW (0) = busy
            check_count = 0
            while True:
                current_state = epdconfig.digital_read(self.busy_pin)
                elapsed = time.time() - start_time
                
                # Exit when pin goes HIGH (1) = idle
                if current_state == 1:
                    logger.debug(f"e-Paper busy release (pin now HIGH/idle) after {elapsed:.2f}s")
                    break
                
                # Check timeout
                if elapsed > timeout:
                    logger.warning(f"e-Paper busy timeout after {elapsed:.1f}s - pin still reads {current_state} (LOW=busy)")
                    logger.warning(f"Pin {self.busy_pin} may be wrong, inverted, or hardware not responding")
                    logger.warning("Try setting EPAPER_BUSY_INVERTED=true if hardware uses HIGH=busy logic")
                    logger.warning("Continuing anyway - display may still work if SPI is functioning")
                    break
                
                # Send command to check status periodically
                if check_count % 10 == 0:  # Every 100ms
                    self.send_command(0x71)
                epdconfig.delay_ms(10)
                check_count += 1
        
    def TurnOnDisplay(self):
        self.send_command(0x12)
        epdconfig.delay_ms(10)
        self.ReadBusy()
        
    def init(self):
        logger.info("Initializing e-Paper module...")
        logger.info(f"Using pins: RST={self.reset_pin}, DC={self.dc_pin}, CS={self.cs_pin}, BUSY={self.busy_pin}")
        
        init_result = epdconfig.module_init()
        if (init_result != 0):
            logger.error(f"module_init() returned {init_result}")
            return -1
        logger.info("Module initialized, resetting display...")
        
        # Check BUSY pin state before reset
        busy_before = epdconfig.digital_read(self.busy_pin)
        logger.info(f"BUSY pin state before reset: {busy_before}")
        
        # EPD hardware init start
        self.reset()
        
        # Check BUSY pin state after reset
        epdconfig.delay_ms(100)  # Give hardware time to respond
        busy_after = epdconfig.digital_read(self.busy_pin)
        logger.info(f"BUSY pin state after reset: {busy_after}")
        
        logger.info("Sending power on command (0x04) and waiting for ready...")
        self.send_command(0x04)
        
        # Check BUSY pin state after power on command
        epdconfig.delay_ms(50)
        busy_after_cmd = epdconfig.digital_read(self.busy_pin)
        logger.info(f"BUSY pin state after 0x04 command: {busy_after_cmd}")
        
        self.ReadBusy() #waiting for the electronic paper IC to release the idle signal
        logger.info("Display ready, configuring panel...")

        self.send_command(0x00)     #panel setting
        self.send_data(0x1f)        # LUT from OTP，KW-BF   KWR-AF    BWROTP 0f   BWOTP 1f

        self.send_command(0x61)     #resolution setting
        self.send_data (0x80)       
        self.send_data (0x01)   
        self.send_data (0x28)   

        self.send_command(0X50) #VCOM AND DATA INTERVAL SETTING     
        self.send_data(0x97)        #WBmode:VBDF 17|D7 VBDW 97 VBDB 57  WBRmode:VBDF F7 VBDW 77 VBDB 37  VBDR B7

        return 0
    
    def SetPartReg(self):

        self.send_command(0x01) #POWER SETTING
        self.send_data(0x03)
        self.send_data(0x00)
        self.send_data(0x2b)
        self.send_data(0x2b)
        self.send_data(0x03)

        self.send_command(0x06) #boost soft start
        self.send_data(0x17)     #A
        self.send_data(0x17)     #B
        self.send_data(0x17)     #C

        self.send_command(0x04)
        self.ReadBusy()

        self.send_command(0x00) #panel setting
        self.send_data(0xbf)     #LUT from OTP，128x296

        self.send_command(0x30) #PLL setting
        self.send_data(0x3a)     # 3a 100HZ   29 150Hz 39 200HZ 31 171HZ

        self.send_command(0x61) #resolution setting
        self.send_data(self.width)
        self.send_data((self.height >> 8) & 0xff)
        self.send_data(self.height & 0xff)

        self.send_command(0x82) #vcom_DC setting
        self.send_data(0x12)

        self.send_command(0X50)
        self.send_data(0x97)
        
        self.send_command(0x20)         # vcom
        self.send_data2(self.lut_vcom1)
        self.send_command(0x21)         # ww --
        self.send_data2(self.lut_ww1)
        self.send_command(0x22)         # bw r
        self.send_data2(self.lut_bw1)
        self.send_command(0x23)         # wb w
        self.send_data2(self.lut_wb1)
        self.send_command(0x24)         # bb b
        self.send_data2(self.lut_bb1)

    def getbuffer(self, image):
        # logger.debug("bufsiz = ",int(self.width/8) * self.height)
        buf = [0xFF] * (int(self.width/8) * self.height)
        image_monocolor = image.convert('1')
        imwidth, imheight = image_monocolor.size
        pixels = image_monocolor.load()
        # logger.debug("imwidth = %d, imheight = %d",imwidth,imheight)
        if(imwidth == self.width and imheight == self.height):
            logger.debug("Vertical")
            for y in range(imheight):
                for x in range(imwidth):
                    # Set the bits for the column of pixels at the current position.
                    if pixels[x, y] == 0:
                        buf[int((x + y * self.width) / 8)] &= ~(0x80 >> (x % 8))
        elif(imwidth == self.height and imheight == self.width):
            logger.debug("Horizontal")
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
            buf[i] = ~image[i]
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
        self.send_command(0X02)         #power off
        self.send_command(0X07)         #deep sleep  
        self.send_data(0xA5)
        
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()

### END OF FILE ###

