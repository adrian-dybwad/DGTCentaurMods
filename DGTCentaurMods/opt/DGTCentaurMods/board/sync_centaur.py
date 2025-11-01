# DGT Centaur Synchronous Board Controller
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# SyncCentaur (sync_centaur.py) was written by Adrian Dybwad 
# with help from Cursor AI. The most amazing tool I've ever used.
# https://github.com/adrian-dybwad/DGTCentaurMods 
# Perhaps it will be merged into the main project some day!
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
import queue
import logging
import sys
import os
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Callable
from types import SimpleNamespace

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.handlers = []

_fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s", "%Y-%m-%d %H:%M:%S")

try:
    _fh = logging.FileHandler("/home/pi/debug.log", mode="w")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
except Exception:
    pass

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.DEBUG)
_ch.setFormatter(_fmt)
logger.addHandler(_ch)


# Unified command registry
@dataclass(frozen=True)
class CommandSpec:
    cmd: bytes
    expected_resp_type: int
    default_data: Optional[bytes] = None

DGT_PIECE_EVENT_RESP = 0x8e  # Identifies a piece detection event

# Response constants (needed before COMMANDS for exports)
# These will be properly exported from COMMANDS below, but we need them here for direct use
DGT_BUS_SEND_CHANGES_RESP = 0x85
DGT_BUS_SEND_STATE_RESP = 0x83
DGT_NOTIFY_EVENTS_RESP = 0xa3

COMMANDS: Dict[str, CommandSpec] = {
    "DGT_BUS_SEND_STATE":     CommandSpec(0x82, 0x83, None),
    "DGT_BUS_SEND_CHANGES":   CommandSpec(0x83, 0x85, None),
    "DGT_SEND_BATTERY_INFO":  CommandSpec(0x98, 0xB5, None),
    "SOUND_GENERAL":          CommandSpec(0xb1, 0xB1, b'\x4c\x08'),
    "SOUND_FACTORY":          CommandSpec(0xb1, 0xB1, b'\x4c\x40'),
    "SOUND_POWER_OFF":        CommandSpec(0xb1, 0xB1, b'\x4c\x08\x48\x08'),
    "SOUND_POWER_ON":         CommandSpec(0xb1, 0xB1, b'\x48\x08\x4c\x08'),
    "SOUND_WRONG":            CommandSpec(0xb1, 0xB1, b'\x4e\x0c\x48\x10'),
    "SOUND_WRONG_MOVE":       CommandSpec(0xb1, 0xB1, b'\x48\x08'),
    "DGT_SLEEP":              CommandSpec(0xb2, 0xB1, b'\x0a'),
    "LED_OFF_CMD":            CommandSpec(0xb0, None, b'\x00'),
    "LED_FLASH_CMD":          CommandSpec(0xb0, None, b'\x05\x0a\x00\x01'),
    "DGT_NOTIFY_EVENTS":      CommandSpec(0x58, 0xa3, None),
    "DGT_RETURN_BUSADRES":    CommandSpec(0x46, 0x90, None),
    "DGT_SEND_TRADEMARK":     CommandSpec(0x97, 0xb4, None),
}

# Fast lookups
CMD_BY_NAME = {name: spec for name, spec in COMMANDS.items()}

# Export response-type constants
globals().update({f"{name}_RESP": spec.expected_resp_type for name, spec in COMMANDS.items()})

# Export default data constants
globals().update({f"{name}_DATA": spec.default_data for name, spec in COMMANDS.items()})

# Export name namespace for commands
command = SimpleNamespace(**{name: name for name in COMMANDS.keys()})

# Start-of-packet type bytes
OTHER_START_TYPES = {0x87, 0x93}
START_TYPE_BYTES = {spec.expected_resp_type for spec in COMMANDS.values()} | OTHER_START_TYPES

DGT_BUTTON_CODES = {
    0x01: "BACK",
    0x10: "TICK",
    0x08: "UP",
    0x02: "DOWN",
    0x40: "HELP",
    0x04: "PLAY",
    0x06: "LONG_PLAY",
}

from enum import IntEnum
KEY_NAME_BY_CODE = dict(DGT_BUTTON_CODES)
KEY_CODE_BY_NAME = {v: k for k, v in KEY_NAME_BY_CODE.items()}
Key = IntEnum('Key', {name: code for name, code in KEY_CODE_BY_NAME.items()})


__all__ = ['SyncCentaur', 'DGT_BUS_SEND_CHANGES', 'DGT_SEND_BATTERY_INFO', 'DGT_BUTTON_CODES', 'command']


class SyncCentaur:
    """DGT Centaur Synchronous Board Controller
    
    Simplified synchronous version of AsyncCentaur with:
    - Blocking request/response only
    - FIFO request queue
    - Unsolicited message handling (piece events, key events)
    - Drop-in replacement for AsyncCentaur
    
    Usage:
        centaur = SyncCentaur(developer_mode=False)
        centaur.wait_ready()
        payload = centaur.request_response("DGT_BUS_SEND_CHANGES", timeout=1.5)
    """
    
    def __init__(self, developer_mode=False, auto_init=True):
        """
        Initialize serial connection to the board.
        
        Args:
            developer_mode: If True, use virtual serial ports via socat
            auto_init: If True, initialize in background thread
        """
        self.ser = None
        self.addr1 = 0x00
        self.addr2 = 0x00
        self.developer_mode = developer_mode
        self.ready = False
        self.listener_running = True
        self.listener_thread = None
        self.response_buffer = bytearray()
        self.packet_count = 0
        self._closed = False
        
        # Key event handling
        self.key_up_queue = queue.Queue(maxsize=128)
        self._last_key = None
        
        # Request queue and synchronization
        self._request_queue = queue.Queue()
        self._current_waiter = None  # {'expected_type': int, 'queue': Queue}
        self._waiter_lock = threading.Lock()
        
        # Piece event listener callback
        self._piece_listener = None
        
        # Callback worker queue for piece events
        self._callback_queue = queue.Queue(maxsize=256)
        self._callback_thread = threading.Thread(target=self._callback_worker, name="piece-callback", daemon=True)
        self._callback_thread.start()
        
        if auto_init:
            init_thread = threading.Thread(target=self.run_background, daemon=False)
            init_thread.start()
    
    def run_background(self, start_key_polling=False):
        """Initialize in background thread"""
        self.listener_running = True
        self.ready = False
        self._initialize()
        
        # Start listener thread
        self.listener_thread = threading.Thread(target=self._listener_thread, daemon=True)
        self.listener_thread.start()
        
        # Start request processor thread
        self._processor_thread = threading.Thread(target=self._request_processor, daemon=True)
        self._processor_thread.start()
        
        # Start discovery
        logging.info("Starting discovery...")
        self._discover_board_address()
    
    def wait_ready(self, timeout=60):
        """
        Wait for initialization to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            bool: True if ready, False if timeout
        """
        start = time.time()
        while not self.ready and time.time() - start < timeout:
            time.sleep(0.1)
        if not self.ready:
            logging.warning(f"Timeout waiting for SyncCentaur initialization (waited {timeout}s)")
        return self.ready
    
    def _initialize(self):
        """Open serial connection based on mode"""
        if self.developer_mode:
            logging.debug("Developer mode enabled - setting up virtual serial port")
            os.system("socat -d -d pty,raw,echo=0 pty,raw,echo=0 &")
            time.sleep(10)
            self.ser = serial.Serial("/dev/pts/2", baudrate=1000000, timeout=5.0)
        else:
            try:
                self.ser = serial.Serial("/dev/serial0", baudrate=1000000, timeout=0.2)
                self.ser.isOpen()
            except:
                self.ser.close()
                self.ser.open()
        
        logging.info("Serial port opened successfully")
    
    def _listener_thread(self):
        """Continuously read from serial and parse packets"""
        logging.info("Listening for serial data...")
        while self.listener_running:
            try:
                byte = self.ser.read(1)
                if not byte:
                    continue
                
                self._process_byte(byte[0])
            except Exception as e:
                logging.error(f"Listener error: {e}")
    
    def _process_byte(self, byte):
        """Process incoming byte and detect packet boundaries"""
        self._handle_orphaned_data_detection(byte)
        self.response_buffer.append(byte)
        
        if self._try_packet_detection(byte):
            return
        
        # Prevent buffer overflow
        if len(self.response_buffer) > 1000:
            self.response_buffer.pop(0)
    
    def _handle_orphaned_data_detection(self, byte):
        """Detect and log orphaned data when new packet starts"""
        HEADER_DATA_BYTES = 4
        if len(self.response_buffer) >= HEADER_DATA_BYTES:
            if self.response_buffer[-HEADER_DATA_BYTES] in START_TYPE_BYTES:
                if self.response_buffer[-HEADER_DATA_BYTES+3] == self.addr1:
                    if byte == self.addr2:
                        if len(self.response_buffer) > HEADER_DATA_BYTES:
                            hex_row = ' '.join(f'{b:02x}' for b in self.response_buffer[:-1])
                            logging.warning(f"[ORPHANED] {hex_row}")
                            self.response_buffer = bytearray(self.response_buffer[-(HEADER_DATA_BYTES):])
    
    def _try_packet_detection(self, byte):
        """Handle checksum-validated packets, returns True if packet complete"""
        if len(self.response_buffer) >= 3:
            len_hi, len_lo = self.response_buffer[1], self.response_buffer[2]
            declared_length = ((len_hi & 0x7F) << 7) | (len_lo & 0x7F)
            actual_length = len(self.response_buffer)
            
            if actual_length == declared_length:
                if len(self.response_buffer) > 5:
                    calculated_checksum = self.checksum(self.response_buffer[:-1])
                    if byte == calculated_checksum:
                        logging.info(f"[P{self.packet_count:03d}] checksummed: {' '.join(f'{b:02x}' for b in self.response_buffer)}")
                        self._on_packet_complete(self.response_buffer)
                        return True
                    else:
                        if self.response_buffer[0] == DGT_NOTIFY_EVENTS_RESP:
                            logging.info(f"DGT_NOTIFY_EVENTS_RESP: {' '.join(f'{b:02x}' for b in self.response_buffer)}")
                            self._handle_key_payload(self.response_buffer[1:])
                            self.response_buffer = bytearray()
                            self.packet_count += 1
                            return True
                        else:
                            logging.info(f"checksum mismatch: {' '.join(f'{b:02x}' for b in self.response_buffer)}")
                            self.response_buffer = bytearray()
                            return False
                else:
                    self._on_packet_complete(self.response_buffer)
                    return True
        return False
    
    def _on_packet_complete(self, packet):
        """Called when complete packet received"""
        self.response_buffer = bytearray()
        self.packet_count += 1
        
        try:
            # Handle discovery
            if not self.ready:
                self._discover_board_address(packet)
                return
            
            # Try delivering to waiter
            if self._try_deliver_to_waiter(packet):
                return
            
            # Handle unsolicited messages
            self._route_packet_to_handler(packet)
        finally:
            # Re-enable notifications after every packet (like AsyncCentaur)
            if self.ready:
                if packet[0] == DGT_PIECE_EVENT_RESP:
                    self.sendPacket(command.DGT_BUS_SEND_CHANGES)
                else:
                    self.sendPacket(command.DGT_NOTIFY_EVENTS)
    
    def _try_deliver_to_waiter(self, packet):
        """Try to deliver packet to waiting request, returns True if delivered"""
        with self._waiter_lock:
            if self._current_waiter is not None:
                expected_type = self._current_waiter.get('expected_type')
                if expected_type == packet[0]:
                    payload = self._extract_payload(packet)
                    q = self._current_waiter.get('queue')
                    self._current_waiter = None
                    if q is not None:
                        try:
                            q.put_nowait(payload)
                        except Exception:
                            pass
                        return True
        return False
    
    def _route_packet_to_handler(self, packet):
        """Route unsolicited packets to appropriate handler"""
        try:
            payload = self._extract_payload(packet)
            if packet[0] == DGT_BUS_SEND_CHANGES_RESP:
                self._handle_board_payload(payload)
            elif packet[0] == DGT_PIECE_EVENT_RESP:
                # Do nothing - the finally block will send DGT_BUS_SEND_CHANGES
                # which will return the actual move data in a DGT_BUS_SEND_CHANGES_RESP packet
                logging.debug(f"Piece event detected (0x8e), waiting for DGT_BUS_SEND_CHANGES response")
            elif packet[0] == DGT_BUS_SEND_STATE_RESP:
                logging.debug(f"Unsolicited board state packet (0x83)")
            else:
                logging.info(f"Unknown packet type: {' '.join(f'{b:02x}' for b in packet)}")
        except Exception as e:
            logging.error(f"Error routing packet: {e}")
    
    def _handle_board_payload(self, payload: bytes):
        """Handle piece movement events"""
        try:
            if len(payload) == 0:
                return
            
            time_bytes = self._extract_time_from_payload(payload)
            hex_row = ' '.join(f'{b:02x}' for b in payload)
            logging.info(f"[P{self.packet_count:03d}] {hex_row}")
            
            # Parse and dispatch piece events
            i = 0
            while i < len(payload) - 1:
                piece_event = payload[i]
                if piece_event in (0x40, 0x41):
                    piece_event = 0 if piece_event == 0x40 else 1
                    field_hex = payload[i + 1]
                    try:
                        square = self.rotateFieldHex(field_hex)
                        time_in_seconds = self._get_seconds_from_time_bytes(time_bytes)
                        logging.info(f"[P{self.packet_count:03d}] piece_event={'LIFT' if piece_event == 0 else 'PLACE'} field_hex={field_hex} square={square} time={time_in_seconds}")
                        
                        if self._piece_listener is not None:
                            args = (piece_event, field_hex, square, time_in_seconds)
                            try:
                                self._callback_queue.put_nowait((self._piece_listener, args))
                            except queue.Full:
                                logging.error("[SyncCentaur] callback queue full, dropping piece event")
                    except Exception as e:
                        logging.error(f"Error processing piece event: {e}")
                    i += 2
                else:
                    i += 1
        except Exception as e:
            logging.error(f"Error handling board payload: {e}")
    
    def _handle_key_payload(self, payload: bytes):
        """Handle key press events"""
        try:
            logging.info(f"[P{self.packet_count:03d}] handle_key_payload: {' '.join(f'{b:02x}' for b in payload)}")
            if len(payload) > 0:
                idx, code_val, is_down = self._find_key_event_in_payload(payload)
                if idx is not None:
                    base_name = DGT_BUTTON_CODES.get(code_val, f"0x{code_val:02x}")
                    logging.info(f"[P{self.packet_count:03d}] {base_name} {'↓' if is_down else '↑'}")
                    
                    if not is_down:
                        key = Key(code_val)
                        self._last_key = key
                        try:
                            self.key_up_queue.put_nowait(key)
                        except queue.Full:
                            pass
        except Exception as e:
            logging.error(f"Error handling key payload: {e}")
    
    def _callback_worker(self):
        """Run piece-event callbacks off the serial thread"""
        while True:
            try:
                item = self._callback_queue.get()
                if not item:
                    continue
                fn, args = item
                try:
                    fn(*args)
                except Exception as e:
                    logging.error(f"[SyncCentaur] piece callback error: {e}")
            except Exception as e:
                logging.error(f"[SyncCentaur] callback worker loop error: {e}")
    
    def _request_processor(self):
        """Process requests from FIFO queue"""
        while self.listener_running:
            try:
                # Get next request from queue (blocking)
                request = self._request_queue.get(timeout=0.1)
                if request is None:
                    continue
                
                command_name, data, timeout, result_queue = request
                
                # Send command and wait for response
                try:
                    payload = self._execute_request(command_name, data, timeout)
                    result_queue.put(('success', payload))
                except Exception as e:
                    result_queue.put(('error', e))
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Request processor error: {e}")
    
    def _execute_request(self, command_name: str, data: Optional[bytes], timeout: float):
        """Execute a single request synchronously"""
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)
        expected_type = spec.expected_resp_type
        
        # If no response expected, just send and return
        if expected_type is None:
            self._send_packet(command_name, eff_data)
            return b''
        
        # Create waiter
        result_queue = queue.Queue(maxsize=1)
        with self._waiter_lock:
            self._current_waiter = {'expected_type': expected_type, 'queue': result_queue}
        
        # Send command
        self._send_packet(command_name, eff_data)
        
        # Wait for response
        try:
            payload = result_queue.get(timeout=timeout)
            return payload
        except queue.Empty:
            # Timeout
            with self._waiter_lock:
                if self._current_waiter is not None and self._current_waiter.get('queue') is result_queue:
                    self._current_waiter = None
            logging.info(f"Request timeout for {command_name}")
            return None
    
    def request_response(self, command_name: str, data: Optional[bytes]=None, timeout=2.0, callback=None, raw_len: Optional[int]=None, retries=0):
        """
        Send a command and wait for response (blocking).
        
        Args:
            command_name: command name to send (e.g., "DGT_BUS_SEND_CHANGES")
            data: optional payload bytes
            timeout: seconds to wait for response
            callback: not supported (for compatibility only)
            raw_len: not supported (for compatibility only)
            retries: not supported (for compatibility only)
            
        Returns:
            bytes: payload of response or None on timeout
        """
        if not isinstance(command_name, str):
            raise TypeError("request_response requires a command name (str)")
        
        # Queue the request
        result_queue = queue.Queue(maxsize=1)
        self._request_queue.put((command_name, data, timeout, result_queue))
        
        # Wait for result
        try:
            status, result = result_queue.get(timeout=timeout + 1.0)
            if status == 'success':
                return result
            else:
                raise result
        except queue.Empty:
            logging.error(f"Request queue timeout for {command_name}")
            return None
    
    def wait_for_key_up(self, timeout=None, accept=None):
        """
        Block until a key-up event is received.
        
        Args:
            timeout: seconds to wait, or None to wait forever
            accept: optional filter of keys (list/set/tuple of codes or names)
            
        Returns:
            Key object on success, or None on timeout
        """
        deadline = (time.time() + timeout) if timeout is not None else None
        while True:
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.time())
                if remaining == 0.0:
                    return None
            try:
                key = self.key_up_queue.get(timeout=remaining)
            except queue.Empty:
                return None
            
            if not accept:
                return key
            
            if isinstance(accept, (set, list, tuple)):
                if key in accept:
                    return key
            else:
                if key == accept:
                    return key
    
    def get_and_reset_last_key(self):
        """
        Non-blocking: return the last key-up event and reset it.
        Returns None if no key-up has been recorded since last call.
        """
        last_key = self._last_key
        self._last_key = None
        return last_key
    
    def _send_packet(self, command_name: str, data: Optional[bytes]):
        """Send a packet to the board"""
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        
        # Use passed data if provided, otherwise use default_data from command spec
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)
        tosend = self._build_packet(spec.cmd, eff_data)
        logging.info(f"sendPacket: {command_name} ({spec.cmd:02x}) {' '.join(f'{b:02x}' for b in tosend[:16])}")
        self.ser.write(tosend)
        
        # Re-enable notifications after commands that don't expect responses
        if self.ready and spec.expected_resp_type is None and command_name != command.DGT_NOTIFY_EVENTS:
            # Note: Must call _send_packet directly to avoid recursion
            spec_notify = CMD_BY_NAME[command.DGT_NOTIFY_EVENTS]
            notify_data = spec_notify.default_data if spec_notify.default_data is not None else None
            tosend_notify = self._build_packet(spec_notify.cmd, notify_data)
            self.ser.write(tosend_notify)
    
    def sendPacket(self, command_name: str, data: Optional[bytes] = None):
        """
        Send a packet to the board using a command name (for compatibility).
        
        Args:
            command_name: command name in COMMANDS
            data: bytes for data payload
        """
        if not isinstance(command_name, str):
            raise TypeError("sendPacket requires a command name (str)")
        self._send_packet(command_name, data)
    
    def _build_packet(self, command, data):
        """Build a complete packet with command, addresses, data, and checksum"""
        tosend = bytearray([command])
        if data is not None:
            len_packet = len(data) + 6
            len_hi = (len_packet >> 7) & 0x7F
            len_lo = len_packet & 0x7F
            tosend.append(len_hi)
            tosend.append(len_lo)
        tosend.append(self.addr1 & 0xFF)
        tosend.append(self.addr2 & 0xFF)
        if data is not None:
            tosend.extend(data)
        tosend.append(self.checksum(tosend))
        return tosend
    
    def checksum(self, barr):
        """Calculate checksum for packet (sum of all bytes mod 128)"""
        csum = sum(bytes(barr))
        return csum % 128
    
    def _extract_payload(self, packet):
        """Extract payload bytes from packet (after addr2, before checksum)"""
        if not packet or len(packet) < 6:
            return b''
        return bytes(packet[5:len(packet)-1])
    
    def _extract_time_from_payload(self, payload: bytes) -> bytes:
        """Return time bytes prefix from payload (before first 0x40/0x41 marker)"""
        out = bytearray()
        for b in payload:
            if b in (0x40, 0x41):
                break
            out.append(b)
        return bytes(out)
    
    def _get_seconds_from_time_bytes(self, time_bytes):
        """Convert time bytes to seconds"""
        if len(time_bytes) == 0:
            return 0
        time_in_seconds = time_bytes[0] / 256.0
        time_in_seconds += time_bytes[1] if len(time_bytes) > 1 else 0
        time_in_seconds += time_bytes[2] * 60 if len(time_bytes) > 2 else 0
        time_in_seconds += time_bytes[3] * 3600 if len(time_bytes) > 3 else 0
        return time_in_seconds
    
    def _find_key_event_in_payload(self, payload: bytes):
        """
        Detect a key event within a key payload.
        Returns (code_index, code_value, is_down) or (None, None, None)
        """
        for i in range(0, len(payload) - 5):
            if (payload[i] == 0x00 and
                payload[i+1] == 0x14 and
                payload[i+2] == 0x0a and
                payload[i+3] == 0x05):
                first = payload[i+4]
                second = payload[i+5] if i+5 < len(payload) else 0x00
                if first != 0x00:
                    return (i + 4, first, True)
                if first == 0x00 and second != 0x00:
                    return (i + 5, second, False)
                break
        return (None, None, None)
    
    def _discover_board_address(self, packet=None):
        """Non-blocking board discovery state machine"""
        if self.ready:
            return
        
        if packet is None:
            logging.info("Discovery: STARTING")
            spec = CMD_BY_NAME[command.DGT_RETURN_BUSADRES]
            data = spec.default_data if spec.default_data is not None else None
            tosend = self._build_packet(spec.cmd, data)
            self.ser.write(tosend)
            return
        
        logging.info(f"Discovery: packet: {' '.join(f'{b:02x}' for b in packet)}")
        if packet[0] == 0x90:
            if self.addr1 == 0x00 and self.addr2 == 0x00:
                self.addr1 = packet[3]
                self.addr2 = packet[4]
            else:
                if self.addr1 == packet[3] and self.addr2 == packet[4]:
                    self.ready = True
                    spec = CMD_BY_NAME[command.DGT_NOTIFY_EVENTS]
                    data = spec.default_data if spec.default_data is not None else None
                    tosend = self._build_packet(spec.cmd, data)
                    self.ser.write(tosend)
                    logging.info(f"Discovery: READY - addr1={hex(self.addr1)}, addr2={hex(self.addr2)}")
                else:
                    logging.info(f"Discovery: ERROR - address mismatch")
                    self.addr1 = 0x00
                    self.addr2 = 0x00
                    spec = CMD_BY_NAME[command.DGT_RETURN_BUSADRES]
                    data = spec.default_data if spec.default_data is not None else None
                    tosend = self._build_packet(spec.cmd, data)
                    self.ser.write(tosend)
    
    def cleanup(self, leds_off: bool = True):
        """Cleanup resources"""
        if self._closed:
            return
        
        self.listener_running = False
        
        if leds_off:
            try:
                self.ledsOff()
            except Exception:
                pass
        
        # Stop threads
        try:
            if self.listener_thread and self.listener_thread.is_alive():
                self.listener_thread.join(timeout=1.0)
        except Exception:
            pass
        
        # Close serial
        self.ready = False
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        
        self._closed = True
        logging.info("SyncCentaur cleaned up")
    
    def rotateField(self, field):
        """Convert field index from board coordinate system"""
        lrow = (field // 8)
        lcol = (field % 8)
        newField = (7 - lrow) * 8 + lcol
        return newField
    
    def rotateFieldHex(self, fieldHex):
        """Convert hex field to board coordinate system"""
        squarerow = (fieldHex // 8)
        squarecol = (fieldHex % 8)
        field = (7 - squarerow) * 8 + squarecol
        return field
    
    def convertField(self, field):
        """Convert field index to chess notation (e.g., 'e4')"""
        square = chr((ord('a') + (field % 8))) + chr(ord('1') + (field // 8))
        return square
    
    def notify_keys_and_pieces(self):
        """Enable notifications for keys and pieces"""
        logging.info(f"notify_keys_and_pieces")
        self.sendPacket(command.DGT_NOTIFY_EVENTS)
    
    def clearBoardData(self):
        """Clear board movement data"""
        logging.info(f"clearBoardData")
        self.sendPacket(command.DGT_BUS_SEND_CHANGES)
    
    def beep(self, sound_name: str):
        """Make a beep sound by name"""
        logging.info(f"beep: {sound_name}")
        self.sendPacket(sound_name)
    
    def ledsOff(self):
        """Turn off all LEDs"""
        logging.info(f"ledsOff")
        self.sendPacket(command.LED_OFF_CMD)
    
    def ledArray(self, inarray, speed=3, intensity=5):
        """Light LEDs in array with given speed and intensity"""
        logging.info(f"ledArray: {inarray} {speed} {intensity}")
        data = bytearray([0x05])
        data.append(speed)
        data.append(0)
        data.append(intensity)
        for i in range(0, len(inarray)):
            data.append(self.rotateField(inarray[i]))
        self.sendPacket(command.LED_FLASH_CMD, data)
    
    def ledFromTo(self, lfrom, lto, intensity=5):
        """Light up from and to LEDs for move indication"""
        logging.info(f"ledFromTo: {lfrom} {lto} {intensity}")
        data = bytearray([0x05, 0x03, 0x00])
        data.append(intensity)
        data.append(self.rotateField(lfrom))
        data.append(self.rotateField(lto))
        self.sendPacket(command.LED_FLASH_CMD, data)
    
    def led(self, num, intensity=5):
        """Flash a specific LED"""
        logging.info(f"led: {num} {intensity}")
        data = bytearray([0x05, 0x0a, 0x01])
        data.append(intensity)
        data.append(self.rotateField(num))
        self.sendPacket(command.LED_FLASH_CMD, data)
    
    def ledFlash(self):
        """Flash the last LED lit"""
        logging.info(f"ledFlash")
        self.sendPacket(command.LED_FLASH_CMD)
    
    def sleep(self):
        """Sleep the controller"""
        logging.info(f"sleep")
        self.sendPacket(command.DGT_SLEEP)

