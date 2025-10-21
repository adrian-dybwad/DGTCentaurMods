# DGT Centaur Serial Helper Functions
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import serial
import time
import logging
import sys
import os
import threading

try:
    logging.basicConfig(level=logging.DEBUG, filename="/home/pi/debug.log", filemode="w")
except:
    logging.basicConfig(level=logging.DEBUG)


class SerialHelper:
    """Helper class for managing serial communication with DGT Centaur board
    
    Examples:
        
         Non-blocking initialization (returns immediately):
            helper = SerialHelper(developer_mode=False)
            helper.wait_ready()
            helper.sendPacket(b'\x83', b'')
        
        Blocking initialization:
            helper = SerialHelper(developer_mode=False, auto_init=False)
            helper._init_background()
            helper.sendPacket(b'\x83', b'')
    """
    
    def __init__(self, developer_mode=False, auto_init=True):
        """
        Initialize serial connection to the board.
        
        Args:
            developer_mode (bool): If True, use virtual serial ports via socat
            auto_init (bool): If True, initialize in background thread (non-blocking)
        """
        self.ser = None
        self.addr1 = 0x00
        self.addr2 = 0x00
        self.developer_mode = developer_mode
        self.ready = False
        self.listener_running = True
        self.listener_thread = None
        
        if auto_init:
            init_thread = threading.Thread(target=self._init_background, daemon=False)
            init_thread.start()
    
    def _init_background(self):
        """Initialize in background thread"""
        self._initialize_serial()
        self._discover_board_address()
        self.listener_thread = threading.Thread(target=self._listener_thread, daemon=True)
        self.listener_thread.start()
        self.ready = True
        self.sendPacket(b'\x94', b'')
        logging.debug("SerialHelper initialization complete and ready")
    
    def wait_ready(self, timeout=60):
        """
        Wait for initialization to complete.
        
        Args:
            timeout (int): Maximum time to wait in seconds
            
        Returns:
            bool: True if ready, False if timeout
        """
        start = time.time()
        while not self.ready and time.time() - start < timeout:
            time.sleep(0.1)
        if not self.ready:
            logging.warning(f"Timeout waiting for SerialHelper initialization (waited {timeout}s)")
        return self.ready
    
    def _listener_thread(self):
        """Continuously listen for data on the serial port and print it"""
        logging.debug("Serial listener thread started")
        while self.listener_running:
            try:
                data = self.ser.read(1000)
                if data:
                    if data != self.buildPacket(b'\xb1\x00\x06', b'') and self.ready: #Response to x94
                        print(f"KEY: {data}")
                    if data != self.buildPacket(b'\x85\x00\x06', b'') and self.ready: #Response to x83                         
                        print(f"PIECE: {data}")
                    if self.ready:
                        self.sendPacket(b'\x94', b'') #Key detection enabled
                        self.sendPacket(b'\x83', b'') #Piece detection enabled

            except:
                if self.listener_running:
                    time.sleep(0.1)
    
    def stop_listener(self):
        """Stop the serial listener thread"""
        self.listener_running = False
        logging.debug("Serial listener thread stopped")
    
    def _initialize_serial(self):
        """Open serial connection based on mode"""
        if self.developer_mode:
            logging.debug("Developer mode enabled - setting up virtual serial port")
            os.system("socat -d -d pty,raw,echo=0 pty,raw,echo=0 &")
            time.sleep(10)
            self.ser = serial.Serial("/dev/pts/2", baudrate=1000000, timeout=0.2)
        else:
            try:
                self.ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=0.2)
                self.ser.isOpen()
            except:
                self.ser.close()
                self.ser.open()
        
        logging.debug("Serial port opened successfully")
    
    def checksum(self, barr):
        """
        Calculate checksum for packet (sum of all bytes mod 128).
        
        Args:
            barr: bytearray to calculate checksum for
            
        Returns:
            int: checksum value
        """
        csum = 0
        for c in bytes(barr):
            csum += c
        barr_csum = (csum % 128)
        return barr_csum
    
    def buildPacket(self, command, data):
        """
        Build a complete packet with command, addresses, data, and checksum.
        
        Args:
            command: bytes for command
            data: bytes for data payload
            
        Returns:
            bytearray: complete packet ready to send
        """
        tosend = bytearray(command + self.addr1.to_bytes(1, byteorder='big') + 
                          self.addr2.to_bytes(1, byteorder='big') + data)
        tosend.append(self.checksum(tosend))
        return tosend
    
    def sendPacket(self, command, data):
        """
        Send a packet to the board.
        
        Args:
            command: bytes for command
            data: bytes for data payload
        """
        tosend = self.buildPacket(command, data)
        self.ser.write(tosend)
    
    def readSerial(self, num_bytes=1000):
        """
        Read data from serial port.
        
        Args:
            num_bytes (int): number of bytes to attempt to read
            
        Returns:
            bytes: data read from serial port
        """
        try:
            return self.ser.read(num_bytes)
        except:
            return self.ser.read(num_bytes)
    
    def _discover_board_address(self):
        """
        Discover the board address by sending initialization commands.
        This replicates the address discovery sequence from board.py.
        """
        logging.debug("Detecting board address")
        
        try:
            self.readSerial(1000)
        except:
            self.readSerial(1000)
        
        tosend = bytearray(b'\x4d')
        self.ser.write(tosend)
        try:
            self.readSerial(1000)
        except:
            self.readSerial(1000)
        logging.debug('Sent payload 1 (0x4d)')
        
        tosend = bytearray(b'\x4e')
        self.ser.write(tosend)
        try:
            self.readSerial(1000)
        except:
            self.readSerial(1000)
        logging.debug('Sent payload 2 (0x4e)')
        
        logging.debug('Serial is open. Waiting for response.')
        resp = ""
        timeout = time.time() + 60
        
        while len(resp) < 4 and time.time() < timeout:
            if self.developer_mode:
                break
            
            tosend = bytearray(b'\x87\x00\x00\x07')
            self.ser.write(tosend)
            try:
                resp = self.ser.read(1000)
            except:
                resp = self.ser.read(1000)
            
            if len(resp) > 3:
                self.addr1 = resp[3]
                self.addr2 = resp[4]
                logging.debug("Discovered board address: %s%s", hex(self.addr1), hex(self.addr2))
                break
        else:
            if not self.developer_mode:
                logging.debug('FATAL: No response from serial')
                sys.exit(1)
    
    def initialize_device(self):
        """
        Send initialization commands to prepare the device.
        Uses the same packet construction as board.py initialization.
        """
        logging.debug("Initializing device with discovered addresses")
        
        try:
            self.readSerial(1000)
        except:
            self.readSerial(1000)
        
        self.sendPacket(b'\x4d', b'')
        try:
            self.readSerial(1000)
        except:
            self.readSerial(1000)
        logging.debug('Sent initialization payload 1')
        
        self.sendPacket(b'\x4e', b'')
        try:
            self.readSerial(1000)
        except:
            self.readSerial(1000)
        logging.debug('Sent initialization payload 2')
        
        logging.debug('Device initialization complete')
    
    def close(self):
        """Close the serial connection"""
        self.stop_listener()
        if self.ser:
            self.ser.close()
            logging.debug("Serial port closed")

    def ledsOff(self):
        # Switch the LEDs off on the centaur
        self.sendPacket(b'\xb0\x00\x07', b'\x00')
        self.sendPacket(b'\xb0\x00\x07', b'\x01')
