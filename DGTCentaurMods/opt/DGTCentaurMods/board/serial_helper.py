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
import itertools

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
        self.spinner = itertools.cycle(['|', '/', '-', '\\'])
        self.response_buffer = bytearray()
        self.parse_state = "SEEKING_START"
        self.packet_length = 0
        self.extra_data_count = 0
        self.collected_packets = []
        
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
                byte = self.ser.read(1)
                if byte:
                    #resp = bytearray(resp)
                    self.processResponse(byte[0])
                    #if data != self.buildPacket(b'\xb1\x00\x06', b'') and self.ready: #Response to x94
                    #    print(f"KEY: {data}")
                    # if resp != self.buildPacket(b'\x85\x00\x06', b'') and self.ready: #Response to x83                         
                    #     #print(f"PIECE: {resp}")
                    #     if (resp[0] == 133 and resp[1] == 0):
                    #         for x in range(0, len(resp) - 1):
                    #             if (resp[x] == 64):
                    #                 # Calculate the square to 0(a1)-63(h8) so that
                    #                 # all functions match
                    #                 fieldHex = resp[x + 1]
                    #                 #print(f"FIELD HEX: {fieldHex}")
                    #                 lifted = self.rotateFieldHex(fieldHex)
                    #                 print(f"LIFTED: {lifted}")
                    #             if (resp[x] == 65):
                    #                 # Calculate the square to 0(a1)-63(h8) so that
                    #                 # all functions match
                    #                 fieldHex = resp[x + 1]
                    #                 #print(f"FIELD HEX: {fieldHex}")
                    #                 placed = self.rotateFieldHex(fieldHex)
                    #                 print(f"PLACED: {placed}")
                    #print(f"READY: {self.ready}")
                    #if self.ready:
                    #    #self.sendPacket(b'\x94', b'') #Key detection enabled
                    #    self.sendPacket(b'\x83', b'') #Piece detection enabled
                else:
                    print(f"\r{next(self.spinner)}", end='', flush=True)

            except Exception as e:
                logging.error(f"Listener error: {e}")
                #if self.listener_running:
                #    time.sleep(0.1)
    
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
    
# PACKET 1 (trimmed before next 85 00):
# 85 00 0e 06 50 16 3a 40 28 18 01 41 30 2b 93 00 05 05 07
# PACKET 2 (trimmed before next 85 00):
# 85 00 13 06 50 2d 2c 0d 40 30 1a 01 41 30 11 09 7c 03 69
# PACKET 3 (incomplete, stops at):
# 85 00 13 06 50 28 16 01 40 28 1e 01 41 20 13 04 7c 03 2b


    def processResponse(self, byte):
        """
        Process incoming byte and construct packets.
        Supports two packet formats:
        
        Format 1 (old): [data...][addr1][addr2][checksum]
        Format 2 (new): [0x85][0x00][data...][addr1][addr2][checksum]
        
        Both have [addr1][addr2][checksum] pattern, but new format may have extra data following.
        """
        print(f"[PROCESS_RESPONSE] Processing byte: {byte}")
        self.response_buffer.append(byte)
        
        # Detect new packet start (85 00) and request more data
        if byte == 0x00 and self.response_buffer[-2] == 0x85:
            print(f"\n{'='*80}")
            print(f"[NEW PACKET START] 0x85 detected - requesting more data via sendPacket(b'\\x83', b'')")
            self.sendPacket(b'\x83', b'')
        
        # Check old format
        if len(self.response_buffer) >= 3:
            if (self.response_buffer[-3] == self.addr1 and 
                self.response_buffer[-2] == self.addr2):
                calculated_checksum = self.checksum(self.response_buffer[:-1])
                if self.response_buffer[-1] == calculated_checksum:
                    print(f"[OLD_FORMAT] Valid packet: {self.response_buffer.hex()}")
                    self.on_packet_complete(self.response_buffer)
                else:
                    print(f"[OLD_FORMAT] Invalid checksum: {self.response_buffer.hex()}")
                self.response_buffer = bytearray()
                self.parse_state = "SEEKING_START"
                return
        
        # Check for new format with 0x85 start
        if self.parse_state == "SEEKING_START":
            if byte == 0x85:
                print(f"[STATE] Found packet start (0x85)")
                self.response_buffer = bytearray([byte])
                self.parse_state = "VERIFY_ZERO"
            else:
                # If buffer gets too large and no match, trim old bytes
                if len(self.response_buffer) > 100:
                    self.response_buffer.pop(0)
        
        elif self.parse_state == "VERIFY_ZERO":
            if byte == 0x00:
                print(f"[STATE] Verified second byte (0x00)")
                self.parse_state = "COLLECTING_UNTIL_END"
            else:
                print(f"[VERIFY_ZERO] Invalid second byte: {byte}, resetting")
                self.parse_state = "SEEKING_START"
                self.response_buffer = bytearray()
        
        elif self.parse_state == "COLLECTING_UNTIL_END":
            # Keep collecting until we find [addr1][addr2][valid_checksum] at the end
            bytes_collected = len(self.response_buffer) - 2
            print(f"[COLLECTING_UNTIL_END] Collected {bytes_collected} bytes (buffer: {self.response_buffer.hex()})")
            
            if len(self.response_buffer) >= 5:
                if (self.response_buffer[-3] == self.addr1 and 
                    self.response_buffer[-2] == self.addr2):
                    calculated_checksum = self.checksum(self.response_buffer[:-1])
                    if self.response_buffer[-1] == calculated_checksum:
                        print(f"[NEW_FORMAT] Found end pattern, checking for extra data...")
                        self.parse_state = "READ_EXTRA_COUNT"
        
        elif self.parse_state == "READ_EXTRA_COUNT":
            self.extra_data_count = 14
            print(f"[READ_EXTRA_COUNT] Using fixed extra data count: {self.extra_data_count}")
            self.parse_state = "COLLECTING_EXTRA_DATA"
        #85 00 0a 06 50 11 02 41 29 62 85 00 06 06 50 61
        elif self.parse_state == "COLLECTING_EXTRA_DATA":
            extra_collected = len(self.response_buffer) - len(bytearray(self.response_buffer[:-self.extra_data_count]))
            print(f"[COLLECTING_EXTRA_DATA] Collected {extra_collected}/{self.extra_data_count} extra bytes")
            if extra_collected >= self.extra_data_count:
                print(f"[NEW_FORMAT] Valid packet (with extra data): {self.response_buffer.hex()}")
                self.on_packet_complete(self.response_buffer)
                self.response_buffer = bytearray()
                self.parse_state = "SEEKING_START"
                self.extra_data_count = 0
    
    def _validate_packet(self):
        """Validate packet checksum and process if valid"""
        # Checksum is calculated on all bytes except the last one
        calculated_checksum = self.checksum(self.response_buffer[:-1])
        received_checksum = self.response_buffer[-1]
        
        print(f"[VALIDATE] Checksum - Expected: {calculated_checksum}, Received: {received_checksum}")
        
        if calculated_checksum == received_checksum:
            print(f"[VALIDATE] VALID PACKET: {self.response_buffer.hex()}")
            self.on_packet_complete(self.response_buffer)
            self._parse_piece_events(self.response_buffer)
        else:
            print(f"[VALIDATE] INVALID CHECKSUM")
            logging.warning(f"Invalid checksum. Expected {calculated_checksum}, got {received_checksum}")
    
    def _parse_piece_events(self, packet):
        """
        Parse piece events from a complete packet.
        Looks for piece lift (0x40) and piece placed (0x41) codes.
        """
        print(f"[PARSE_EVENTS] Parsing packet for piece events")
        for x in range(0, len(packet) - 1):
            if packet[x] == 0x40:
                fieldHex = packet[x + 1]
                square = self.rotateFieldHex(fieldHex)
                field_name = self.convertField(square)
                print(f"[EVENT] PIECE LIFTED from {field_name} (hex: {fieldHex})")
            elif packet[x] == 0x41:
                fieldHex = packet[x + 1]
                square = self.rotateFieldHex(fieldHex)
                field_name = self.convertField(square)
                print(f"[EVENT] PIECE PLACED on {field_name} (hex: {fieldHex})")
    

    def on_packet_complete(self, packet):
        """Called when a complete valid packet is received"""
        self.collected_packets.append(packet)
        packet_num = len(self.collected_packets)
        
        print(f"\n[PACKET #{packet_num}]")
        print(f"HEX: {packet.hex()}")
        print(f"BYTES: {' '.join(f'{b:02x}' for b in packet)}")
        print(f"LENGTH: {len(packet)}")
        
        self.extract_piece_events_detailed(packet)
        
        print(f"{'='*80}\n")
        
        self.sendPacket(b'\x83', b'')

    def extract_piece_events_detailed(self, packet):
        """Extract and display piece events in detail"""
        print("[EVENTS]")
        events_found = False
        for x in range(len(packet)-1):
            if packet[x] == 0x40:
                fieldHex = packet[x + 1]
                square = self.rotateFieldHex(fieldHex)
                field_name = self.convertField(square)
                print(f"  Position {x}: LIFTED from {field_name} (hex: {fieldHex:02x}, decimal: {fieldHex})")
                events_found = True
            elif packet[x] == 0x41:
                fieldHex = packet[x + 1]
                square = self.rotateFieldHex(fieldHex)
                field_name = self.convertField(square)
                print(f"  Position {x}: PLACED on {field_name} (hex: {fieldHex:02x}, decimal: {fieldHex})")
                events_found = True
        if not events_found:
            print("  (No piece events found)")
    
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

    def rotateField(self, field):
        lrow = (field // 8)
        lcol = (field % 8)
        newField = (7 - lrow) * 8 + lcol
        return newField

    def rotateFieldHex(self, fieldHex):
        squarerow = (fieldHex // 8)
        squarecol = (fieldHex % 8)
        field = (7 - squarerow) * 8 + squarecol
        return field

