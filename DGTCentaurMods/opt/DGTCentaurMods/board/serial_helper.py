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


"""
DGT Centaur Serial Protocol - Packet Structure

All packets follow this structure:
    <type1> <type2> <length> <addr1> <addr2> <data...> <checksum>

Where:
    type1, type2 (bytes 0-1): Protocol type identifier, typically 0x85 0x00 for new format
    length (byte 2): Total packet length in bytes, including all fields up to and including checksum
    addr1 (byte 3): Board address 1 (e.g., 0x06)
    addr2 (byte 4): Board address 2 (e.g., 0x50)
    data (bytes 5 to n-1): Variable-length payload (piece events, responses, etc.)
    checksum (byte n): Last byte = sum of all previous bytes mod 128

Examples:
    "No piece" response: 85 00 06 06 50 61
        - Length = 6 bytes (entire packet)
        - No data payload
        - Checksum: (0x85 + 0x00 + 0x06 + 0x06 + 0x50) % 128 = 0x61
    
    Piece event: 85 00 0a 06 50 18 0c 40 30 79
        - Length = 10 bytes
        - Data = 18 0c 40 30 (4 bytes of piece event info)
        - Checksum: (0x85 + 0x00 + 0x0a + 0x06 + 0x50 + 0x18 + 0x0c + 0x40 + 0x30) % 128 = 0x79

Parsing Algorithm:
    1. Accumulate bytes into a buffer
    2. For each new byte, calculate checksum of all previous bytes (mod 128)
    3. If incoming byte equals that checksum:
        a. Extract length from buffer[2]
        b. If len(buffer) == declared_length: valid packet found, emit it
        c. Otherwise: false positive, continue accumulating
    4. When 0x85 0x00 sequence detected while buffer has data: log as orphaned, discard
"""


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
        self.discovery_state = "STARTING"
        self.ready = False
        self.listener_running = True
        self.listener_thread = None
        self.spinner = itertools.cycle(['|', '/', '-', '\\'])
        self.response_buffer = bytearray()
        self.packet_count = 0
        
        if auto_init:
            init_thread = threading.Thread(target=self._init_background, daemon=False)
            init_thread.start()
    
    def _init_background(self):
        """Initialize in background thread"""
        self._initialize_serial()
        self._discover_board_address()
        self.listener_thread = threading.Thread(target=self._listener_thread, daemon=True)
        self.listener_thread.start()
        print("SerialHelper initialization complete - waiting for discovery to complete")
    
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
            self.ser = serial.Serial("/dev/pts/2", baudrate=1000000, timeout=2.0)
        else:
            try:
                self.ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=2.0)
                self.ser.isOpen()
            except:
                self.ser.close()
                self.ser.open()
        
        logging.debug("Serial port opened successfully")
    

    def processResponse(self, byte):
        """
        Process incoming byte - handle discovery state machine first, then normal parsing.
        Supports two packet formats:
        
        Format 1 (old): [data...][addr1][addr2][checksum]
        Format 2 (new): [0x85][0x00][data...][addr1][addr2][checksum]
        
        Both have [addr1][addr2][checksum] pattern at the end.
        Packet boundary is detected when:
        1. Buffer ends with valid [addr1][addr2][checksum], OR
        2. A new 85 00 header is detected (indicating start of next packet)
        """
        # Handle discovery state machine
        if self.discovery_state == "INITIALIZING":
            # Got a response to initial commands, now send discovery packet
            self._discover_board_address()  # Transitions to AWAITING_PACKET
        
        # Detect new packet start sequence (85 00) while buffer has data
        if (len(self.response_buffer) >= 1 and 
            self.response_buffer[-1] == 0x85 and 
            byte == 0x00 and 
            len(self.response_buffer) > 1):
            # Log orphaned data (everything except the 85)
            hex_row = ' '.join(f'{b:02x}' for b in self.response_buffer[:-1])
            print(f"[ORPHANED] {hex_row}")
            self.response_buffer = bytearray([0x85])  # Keep the 85, add the 00 below
        
        #print(f"Processing byte: 0x{byte:02x}")
        self.response_buffer.append(byte)
        
        # Check if this byte is a checksum boundary
        if len(self.response_buffer) >= 2:
            calculated_checksum = self.checksum(self.response_buffer[:-1])
            if byte == calculated_checksum:
                # Verify packet length matches declared length
                if len(self.response_buffer) >= 3:
                    declared_length = self.response_buffer[2]
                    actual_length = len(self.response_buffer)
                    
                    if actual_length == declared_length:
                        # If we're awaiting discovery packet, extract addr1/addr2
                        if self.discovery_state == "AWAITING_PACKET":
                            if len(self.response_buffer) > 4:
                                self.addr1 = self.response_buffer[3]
                                self.addr2 = self.response_buffer[4]
                                self.discovery_state = "READY"
                                self.ready = True
                                print(f"Discovery: READY - addr1={hex(self.addr1)}, addr2={hex(self.addr2)}")
                        
                        # Normal packet processing
                        self.on_packet_complete(self.response_buffer)
                        self.response_buffer = bytearray()
                        return
                else:
                    self.on_packet_complete(self.response_buffer)
                    self.response_buffer = bytearray()
        
        # If buffer gets too large without finding a packet, trim old bytes
        if len(self.response_buffer) > 1000:
            self.response_buffer.pop(0)
    
    def on_packet_complete(self, packet):
        """Called when a complete valid packet is received"""
        self.packet_count += 1
        # Skip printing "no piece" packet
        if packet[:-1] != self.buildPacket(b'\x85\x00\x06', b'')[:-1]:
            hex_row = ' '.join(f'{b:02x}' for b in packet)
            
            # Check if packet has piece events (0x40=lift, 0x41=place)
            has_events = any(packet[i] in (0x40, 0x41) for i in range(5, len(packet) - 1))
            
            # Only display time if there are piece events
            time_str = ""
            if has_events:
                time_signals = self._extract_time_signals(packet)
                if time_signals:
                    time_formatted = self._format_time_display(time_signals)
                    if time_formatted:
                        time_str = f"  [TIME: {time_formatted}]"
            
            print(f"\r[P{self.packet_count:03d}] {hex_row}{time_str}")
            
            # Draw piece events with arrow indicators
            self._draw_piece_events(packet, hex_row, self.packet_count)
        
        # Request next packet if ready
        if self.ready:
            print(f"\r{next(self.spinner)}", end='', flush=True)
            self.sendPacket(b'\x83', b'')

    def _extract_time_signals(self, packet):
        """
        Extract time signals from packet.
        Time signals are any bytes between addr2 (byte 4) and the first lift/place marker (0x40/0x41).
        
        Args:
            packet: The complete packet bytearray
            
        Returns:
            bytearray: Time signal bytes, or empty if none found
        """
        time_signals = bytearray()
        
        # Start searching from byte 5 (after addr2 at byte 4)
        for i in range(5, len(packet) - 1):
            if packet[i] == 0x40 or packet[i] == 0x41:
                # Found first lift/place marker, return time signals collected
                return time_signals
            time_signals.append(packet[i])
        
        return time_signals

    def _format_time_display(self, time_signals):
        """
        Format time signals as human-readable time string.
        Time format: .ss ss mm [hh]
        - Byte 0: Subseconds (0x00-0xFF = 0.00-0.99)
        - Byte 1: Seconds (0-59)
        - Byte 2: Minutes (0-59)
        - Byte 3: Hours (optional, for times > 59:59)
        
        Args:
            time_signals: bytearray with 1-4 bytes
            
        Returns:
            str: Formatted time like "5:03.42" or "1:05:03.42" or empty string if no signals
        """
        if len(time_signals) == 0:
            return ""
        
        subsec = time_signals[0]
        seconds = time_signals[1] if len(time_signals) >= 2 else 0
        minutes = time_signals[2] if len(time_signals) >= 3 else 0
        hours = time_signals[3] if len(time_signals) >= 4 else 0
        
        # Convert subsec to hundredths
        subsec_decimal = subsec / 256.0 * 100
        
        # Format based on highest unit
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}.{int(subsec_decimal):02d}"
        else:
            return f"{minutes}:{seconds:02d}.{int(subsec_decimal):02d}"

    def _draw_piece_events(self, packet, hex_row, packet_num):
        """
        Find and display piece events (lifts and places) with visual arrow indicators.
        
        Args:
            packet: The complete packet bytearray
            hex_row: The hex string representation already printed
            packet_num: The packet number for reference
        """
        try:
            # Find piece events (0x40=lift, 0x41=place) starting after addr2 (byte 5)
            events_to_draw = []
            for i in range(5, len(packet) - 1):
                if packet[i] == 0x40 or packet[i] == 0x41:
                    fieldHex = packet[i + 1]
                    try:
                        square = self.rotateFieldHex(fieldHex)
                        if 0 <= square <= 63:  # Validate square range
                            field_name = self.convertField(square)
                            arrow = "↑" if packet[i] == 0x40 else "↓"
                            hex_col = i * 3  # Point to marker byte (0x40/0x41), not fieldHex
                            events_to_draw.append((hex_col, arrow, field_name))
                    except Exception as e:
                        print(f"Error processing fieldHex {fieldHex}: {e}")
                        continue
            
            # Print arrow line if events found
            if events_to_draw:
                prefix = f"[P{packet_num:03d}] "
                line = " " * (len(prefix) + len(hex_row))
                line_list = list(line)
                
                for hex_col, arrow, field_name in events_to_draw:
                    abs_pos = len(prefix) + hex_col
                    if abs_pos < len(line_list):
                        line_list[abs_pos] = arrow
                        annotation = f" {field_name}"
                        for j, char in enumerate(annotation):
                            pos = abs_pos + 1 + j
                            if pos < len(line_list):
                                line_list[pos] = char
                
                print("".join(line_list).rstrip())
        except Exception as e:
            print(f"Error in _draw_piece_events: {e}")

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
        State machine for non-blocking board address discovery.
        Progresses through STARTING -> INITIALIZING -> AWAITING_PACKET -> READY
        """
        if self.discovery_state == "STARTING":
            print("Discovery: STARTING - sending 0x4d and 0x4e")
            tosend = bytearray(b'\x4d')
            self.ser.write(tosend)
            tosend = bytearray(b'\x4e')
            self.ser.write(tosend)
            self.discovery_state = "INITIALIZING"
            
        elif self.discovery_state == "INITIALIZING":
            print("Discovery: INITIALIZING - sending discovery packet 0x87 0x00 0x00 0x07")
            tosend = bytearray(b'\x87\x00\x00\x07')
            self.ser.write(tosend)
            self.discovery_state = "AWAITING_PACKET"
    
    def _old_discover_board_address(self):
        """
        Discover the board address by sending initialization commands.
        This replicates the address discovery sequence from board.py.
        """
        logging.debug("Detecting board address")
        
        try:
            resp = self.readSerial(1000)
        except:
            resp = self.readSerial(1000)

        print(f"Response 0: {bytearray.fromhex(resp.hex())}")
        
        tosend = bytearray(b'\x4d')
        self.ser.write(tosend)
        try:
            resp = self.readSerial(1000)
        except:
            resp = self.readSerial(1000)
        logging.debug('Sent payload 1 (0x4d)')

        print(f"Response 1: {bytearray.fromhex(resp.hex())}")
        
        tosend = bytearray(b'\x4e')
        self.ser.write(tosend)
        try:
            resp = self.readSerial(1000)
        except:
            resp = self.readSerial(1000)
        logging.debug('Sent payload 2 (0x4e)')
        print(f"Response 2: {bytearray.fromhex(resp.hex())}")
        
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
            
            print(f"Response 3: {bytearray.fromhex(resp.hex())}")

            if len(resp) > 3:
                self.addr1 = resp[3]
                self.addr2 = resp[4]
                logging.debug("Discovered board address: %s%s", hex(self.addr1), hex(self.addr2))
                break
        else:
            if not self.developer_mode:
                logging.debug('FATAL: No response from serial')
                sys.exit(1)
    
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

    def convertField(self, field):
        square = chr((ord('a') + (field % 8))) + chr(ord('1') + (field // 8))
        return square

