# /*****************************************************************************
# * | File        :	  epdconfig.py
# * | Author      :   Waveshare team
# * | Function    :   Hardware underlying interface
# * | Info        :
# *----------------
# * | This version:   V1.2
# * | Date        :   2022-10-29
# * | Info        :   
# ******************************************************************************
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

import os
import logging
import sys
import time
import subprocess

from ctypes import *

logger = logging.getLogger(__name__)


class RaspberryPi:
    # Pin definition - DGT Centaur hardware configuration
    # Can be overridden via environment variables
    # BUSY_PIN determined by monitoring old driver: pin 24 shows activity during display operations
    RST_PIN  = int(os.environ.get("EPAPER_RST_PIN", "12"))
    DC_PIN   = int(os.environ.get("EPAPER_DC_PIN", "16"))
    CS_PIN   = int(os.environ.get("EPAPER_CS_PIN", "18"))
    BUSY_PIN = int(os.environ.get("EPAPER_BUSY_PIN", "24"))  # Changed from 13 to 24 based on monitoring
    PWR_PIN  = int(os.environ.get("EPAPER_PWR_PIN", "18"))  # Default to CS_PIN; power may be always on or controlled elsewhere
    MOSI_PIN = int(os.environ.get("EPAPER_MOSI_PIN", "10"))  # SPI MOSI (usually fixed)
    SCLK_PIN = int(os.environ.get("EPAPER_SCLK_PIN", "11"))  # SPI SCLK (usually fixed)
    
    # SPI bus and device - can be overridden via environment variables
    # Default to SPI bus 1 (spidev1.0) to match the original epaperDriver.so
    SPI_BUS = int(os.environ.get("EPAPER_SPI_BUS", "1"))
    SPI_DEVICE = int(os.environ.get("EPAPER_SPI_DEVICE", "0"))

    def __init__(self):
        import spidev
        import gpiozero
        
        logger.info(f"Initializing ePaper GPIO pins: RST={self.RST_PIN}, DC={self.DC_PIN}, CS={self.CS_PIN}, BUSY={self.BUSY_PIN}, PWR={self.PWR_PIN}")
        logger.info(f"Initializing ePaper SPI: bus={self.SPI_BUS}, device={self.SPI_DEVICE}")
        
        # Initialize SPI
        self.SPI = spidev.SpiDev()
        try:
            self.SPI.open(self.SPI_BUS, self.SPI_DEVICE)
            # Configure SPI mode and speed
            # UC8151 typically uses SPI Mode 0 (CPOL=0, CPHA=0)
            self.SPI.mode = 0
            # Speed: 4MHz is safe, can go up to 10MHz for UC8151
            self.SPI.max_speed_hz = 4000000
            logger.info(f"SPI opened successfully: mode={self.SPI.mode}, speed={self.SPI.max_speed_hz}Hz")
        except Exception as e:
            logger.error(f"Failed to open SPI bus {self.SPI_BUS} device {self.SPI_DEVICE}: {e}")
            raise
        
        # Initialize GPIO pins
        self.GPIO_RST_PIN    = gpiozero.LED(self.RST_PIN)
        self.GPIO_DC_PIN     = gpiozero.LED(self.DC_PIN)
        # self.GPIO_CS_PIN     = gpiozero.LED(self.CS_PIN)
        self.GPIO_PWR_PIN    = gpiozero.LED(self.PWR_PIN)
        # BUSY_PIN needs to be an input - use DigitalInputDevice for better control
        # For UC8151, BUSY is typically active-low (LOW=busy), but may need pull-up resistor
        # Try pull_up=True (internal pull-up) - if pin floats, it will read HIGH
        # If hardware has external pull-up, pull_up=False might be needed
        try:
            from gpiozero import DigitalInputDevice
            # Try with pull-up first - if pin is floating, it will read HIGH
            # If hardware has external pull-up/down, this might conflict, but usually works
            self.GPIO_BUSY_PIN = DigitalInputDevice(self.BUSY_PIN, pull_up=True)
            logger.info(f"BUSY pin {self.BUSY_PIN} configured with pull_up=True")
        except Exception as e:
            logger.warning(f"Failed to use DigitalInputDevice: {e}, falling back to Button")
            # Fallback to Button if DigitalInputDevice not available
            # Button with pull_up=True means it reads HIGH when not pressed (idle)
            self.GPIO_BUSY_PIN = gpiozero.Button(self.BUSY_PIN, pull_up=True)

        

    def digital_write(self, pin, value):
        if pin == self.RST_PIN:
            if value:
                self.GPIO_RST_PIN.on()
            else:
                self.GPIO_RST_PIN.off()
        elif pin == self.DC_PIN:
            if value:
                self.GPIO_DC_PIN.on()
            else:
                self.GPIO_DC_PIN.off()
        # elif pin == self.CS_PIN:
        #     if value:
        #         self.GPIO_CS_PIN.on()
        #     else:
        #         self.GPIO_CS_PIN.off()
        elif pin == self.PWR_PIN:
            if value:
                self.GPIO_PWR_PIN.on()
            else:
                self.GPIO_PWR_PIN.off()

    def digital_read(self, pin):
        if pin == self.BUSY_PIN:
            value = self.GPIO_BUSY_PIN.value
            # gpiozero.Button returns 0 or 1, but we need to ensure it's the actual pin state
            return value
        elif pin == self.RST_PIN:
            # RST_PIN is an LED, not readable - return a default
            return 0
        elif pin == self.DC_PIN:
            # DC_PIN is an LED, not readable - return a default
            return 0
        # elif pin == self.CS_PIN:
        #     return self.CS_PIN.value
        elif pin == self.PWR_PIN:
            # PWR_PIN is an LED, not readable - return a default
            return 0
        else:
            return 0

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        try:
            # Handle both single value and list inputs
            if isinstance(data, (list, tuple)):
                # If it's already a list, use it directly
                self.SPI.writebytes(data)
            else:
                # Single value, wrap in list
                self.SPI.writebytes([int(data)])
        except Exception as e:
            logger.error(f"SPI writebyte failed: {e}, data={data}, type={type(data)}")
            raise

    def spi_writebyte2(self, data):
        try:
            self.SPI.writebytes2(data)
        except Exception as e:
            logger.error(f"SPI writebyte2 failed: {e}")
            raise

    def DEV_SPI_write(self, data):
        self.DEV_SPI.DEV_SPI_SendData(data)

    def DEV_SPI_nwrite(self, data):
        self.DEV_SPI.DEV_SPI_SendnData(data)

    def DEV_SPI_read(self):
        return self.DEV_SPI.DEV_SPI_ReadData()

    def module_init(self, cleanup=False):
        self.GPIO_PWR_PIN.on()
        
        if cleanup:
            find_dirs = [
                os.path.dirname(os.path.realpath(__file__)),
                '/usr/local/lib',
                '/usr/lib',
            ]
            self.DEV_SPI = None
            for find_dir in find_dirs:
                val = int(os.popen('getconf LONG_BIT').read())
                logging.debug("System is %d bit"%val)
                if val == 64:
                    so_filename = os.path.join(find_dir, 'DEV_Config_64.so')
                else:
                    so_filename = os.path.join(find_dir, 'DEV_Config_32.so')
                if os.path.exists(so_filename):
                    self.DEV_SPI = CDLL(so_filename)
                    break
            if self.DEV_SPI is None:
                RuntimeError('Cannot find DEV_Config.so')

            self.DEV_SPI.DEV_Module_Init()

        else:
            # SPI device - use configurable bus and device
            try:
                self.SPI.open(self.SPI_BUS, self.SPI_DEVICE)
                logger.info(f"SPI opened successfully: bus={self.SPI_BUS}, device={self.SPI_DEVICE}")
            except Exception as e:
                logger.error(f"Failed to open SPI bus={self.SPI_BUS}, device={self.SPI_DEVICE}: {e}")
                raise
            self.SPI.max_speed_hz = 4000000
            self.SPI.mode = 0b00
        return 0

    def module_exit(self, cleanup=False):
        logger.debug("spi end")
        self.SPI.close()

        self.GPIO_RST_PIN.off()
        self.GPIO_DC_PIN.off()
        self.GPIO_PWR_PIN.off()
        logger.debug("close 5V, Module enters 0 power consumption ...")
        
        if cleanup:
            self.GPIO_RST_PIN.close()
            self.GPIO_DC_PIN.close()
            # self.GPIO_CS_PIN.close()
            self.GPIO_PWR_PIN.close()
            self.GPIO_BUSY_PIN.close()

        



class JetsonNano:
    # Pin definition
    RST_PIN  = 17
    DC_PIN   = 25
    CS_PIN   = 8
    BUSY_PIN = 24
    PWR_PIN  = 18

    def __init__(self):
        import ctypes
        find_dirs = [
            os.path.dirname(os.path.realpath(__file__)),
            '/usr/local/lib',
            '/usr/lib',
        ]
        self.SPI = None
        for find_dir in find_dirs:
            so_filename = os.path.join(find_dir, 'sysfs_software_spi.so')
            if os.path.exists(so_filename):
                self.SPI = ctypes.cdll.LoadLibrary(so_filename)
                break
        if self.SPI is None:
            raise RuntimeError('Cannot find sysfs_software_spi.so')

        import Jetson.GPIO
        self.GPIO = Jetson.GPIO

    def digital_write(self, pin, value):
        self.GPIO.output(pin, value)

    def digital_read(self, pin):
        return self.GPIO.input(self.BUSY_PIN)

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        self.SPI.SYSFS_software_spi_transfer(data[0])

    def spi_writebyte2(self, data):
        for i in range(len(data)):
            self.SPI.SYSFS_software_spi_transfer(data[i])

    def module_init(self):
        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setwarnings(False)
        self.GPIO.setup(self.RST_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.DC_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.CS_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.PWR_PIN, self.GPIO.OUT)
        self.GPIO.setup(self.BUSY_PIN, self.GPIO.IN)
        
        self.GPIO.output(self.PWR_PIN, 1)
        
        self.SPI.SYSFS_software_spi_begin()
        return 0

    def module_exit(self):
        logger.debug("spi end")
        self.SPI.SYSFS_software_spi_end()

        logger.debug("close 5V, Module enters 0 power consumption ...")
        self.GPIO.output(self.RST_PIN, 0)
        self.GPIO.output(self.DC_PIN, 0)
        self.GPIO.output(self.PWR_PIN, 0)

        self.GPIO.cleanup([self.RST_PIN, self.DC_PIN, self.CS_PIN, self.BUSY_PIN, self.PWR_PIN])


class SunriseX3:
    # Pin definition
    RST_PIN  = 17
    DC_PIN   = 25
    CS_PIN   = 8
    BUSY_PIN = 24
    PWR_PIN  = 18
    Flag     = 0

    def __init__(self):
        import spidev
        import Hobot.GPIO

        self.GPIO = Hobot.GPIO
        self.SPI = spidev.SpiDev()

    def digital_write(self, pin, value):
        self.GPIO.output(pin, value)

    def digital_read(self, pin):
        return self.GPIO.input(pin)

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        self.SPI.writebytes(data)

    def spi_writebyte2(self, data):
        # for i in range(len(data)):
        #     self.SPI.writebytes([data[i]])
        self.SPI.xfer3(data)

    def module_init(self):
        if self.Flag == 0:
            self.Flag = 1
            self.GPIO.setmode(self.GPIO.BCM)
            self.GPIO.setwarnings(False)
            self.GPIO.setup(self.RST_PIN, self.GPIO.OUT)
            self.GPIO.setup(self.DC_PIN, self.GPIO.OUT)
            self.GPIO.setup(self.CS_PIN, self.GPIO.OUT)
            self.GPIO.setup(self.PWR_PIN, self.GPIO.OUT)
            self.GPIO.setup(self.BUSY_PIN, self.GPIO.IN)

            self.GPIO.output(self.PWR_PIN, 1)
        
            # SPI device, bus = 0, device = 0
            self.SPI.open(2, 0)
            self.SPI.max_speed_hz = 4000000
            self.SPI.mode = 0b00
            return 0
        else:
            return 0

    def module_exit(self):
        logger.debug("spi end")
        self.SPI.close()

        logger.debug("close 5V, Module enters 0 power consumption ...")
        self.Flag = 0
        self.GPIO.output(self.RST_PIN, 0)
        self.GPIO.output(self.DC_PIN, 0)
        self.GPIO.output(self.PWR_PIN, 0)

        self.GPIO.cleanup([self.RST_PIN, self.DC_PIN, self.CS_PIN, self.BUSY_PIN], self.PWR_PIN)


# Platform detection with error handling
try:
    if sys.version_info[0] == 2:
        process = subprocess.Popen("cat /proc/cpuinfo | grep Raspberry", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        process = subprocess.Popen("cat /proc/cpuinfo | grep Raspberry", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output, _ = process.communicate()
    if sys.version_info[0] == 2:
        output = output.decode(sys.stdout.encoding) if output else ""
    output = output or ""
except Exception:
    output = ""

try:
    if "Raspberry" in output:
        implementation = RaspberryPi()
    elif os.path.exists('/sys/bus/platform/drivers/gpio-x3'):
        implementation = SunriseX3()
    else:
        implementation = JetsonNano()
    
    for func in [x for x in dir(implementation) if not x.startswith('_')]:
        setattr(sys.modules[__name__], func, getattr(implementation, func))
except Exception as e:
    # If platform detection fails, default to RaspberryPi but log the error
    logger.warning(f"Platform detection failed: {e}, defaulting to RaspberryPi")
    try:
        implementation = RaspberryPi()
        for func in [x for x in dir(implementation) if not x.startswith('_')]:
            setattr(sys.modules[__name__], func, getattr(implementation, func))
    except Exception as e2:
        logger.error(f"Failed to initialize RaspberryPi implementation: {e2}")
        raise

### END OF FILE ###
