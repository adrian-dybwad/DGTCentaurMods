#!/usr/bin/python
# -*- coding:utf-8 -*-

import os
import logging
import sys
import time
import subprocess

logger = logging.getLogger(__name__)

# DGT Centaur pin configuration
RST_PIN = int(os.environ.get('EPAPER_RST_PIN', '12'))
DC_PIN = int(os.environ.get('EPAPER_DC_PIN', '16'))
CS_PIN = int(os.environ.get('EPAPER_CS_PIN', '18'))
BUSY_PIN = int(os.environ.get('EPAPER_BUSY_PIN', '24'))
PWR_PIN = int(os.environ.get('EPAPER_PWR_PIN', '18'))
SPI_BUS = int(os.environ.get('EPAPER_SPI_BUS', '1'))
SPI_DEVICE = int(os.environ.get('EPAPER_SPI_DEVICE', '0'))


class RaspberryPi:
    def __init__(self):
        import spidev
        import gpiozero
        
        self.RST_PIN = RST_PIN
        self.DC_PIN = DC_PIN
        self.CS_PIN = CS_PIN
        self.BUSY_PIN = BUSY_PIN
        self.PWR_PIN = PWR_PIN
        
        self.SPI = spidev.SpiDev()
        self.GPIO_RST_PIN = gpiozero.LED(self.RST_PIN)
        self.GPIO_DC_PIN = gpiozero.LED(self.DC_PIN)
        self.GPIO_PWR_PIN = gpiozero.LED(self.PWR_PIN)
        self.GPIO_BUSY_PIN = gpiozero.DigitalInputDevice(self.BUSY_PIN, pull_up=True)

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
        elif pin == self.PWR_PIN:
            if value:
                self.GPIO_PWR_PIN.on()
            else:
                self.GPIO_PWR_PIN.off()

    def digital_read(self, pin):
        if pin == self.BUSY_PIN:
            return self.GPIO_BUSY_PIN.value
        return 0

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        if isinstance(data, list):
            self.SPI.writebytes(data)
        else:
            self.SPI.writebytes([data])

    def spi_writebyte2(self, data):
        self.SPI.writebytes(data)

    def module_init(self):
        self.GPIO_PWR_PIN.on()
        self.SPI.open(SPI_BUS, SPI_DEVICE)
        self.SPI.max_speed_hz = 4000000
        self.SPI.mode = 0b00
        return 0

    def module_exit(self):
        logger.debug("spi end")
        self.SPI.close()
        self.GPIO_RST_PIN.off()
        self.GPIO_DC_PIN.off()
        self.GPIO_PWR_PIN.off()
        logger.debug("close 5V, Module enters 0 power consumption ...")
        self.GPIO_RST_PIN.close()
        self.GPIO_DC_PIN.close()
        self.GPIO_PWR_PIN.close()
        self.GPIO_BUSY_PIN.close()


if sys.version_info[0] == 2:
    process = subprocess.Popen("cat /proc/cpuinfo | grep Raspberry", shell=True, stdout=subprocess.PIPE)
else:
    process = subprocess.Popen("cat /proc/cpuinfo | grep Raspberry", shell=True, stdout=subprocess.PIPE, text=True)
output, _ = process.communicate()
if sys.version_info[0] == 2:
    output = output.decode(sys.stdout.encoding)

if "Raspberry" in output:
    implementation = RaspberryPi()
else:
    raise RuntimeError("Only Raspberry Pi is supported")

for func in [x for x in dir(implementation) if not x.startswith('_')]:
    setattr(sys.modules[__name__], func, getattr(implementation, func))
