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
import sys
import os
import threading
from dataclasses import dataclass
from typing import Dict, Optional
from types import SimpleNamespace

from DGTCentaurMods.board.logging import log
from DGTCentaurMods.board import time_utils


# Unified command registry
@dataclass(frozen=True)
class CommandSpec:
    cmd: bytes
    expected_resp_type: int
    default_data: Optional[bytes] = None

DGT_PIECE_EVENT_RESP = 0x8e  # Identifies a piece detection event

COMMANDS: Dict[str, CommandSpec] = {
    "DGT_BUS_SEND_87":        CommandSpec(0x87, 0x87), # Sent after initial init but before ADDR1 ADDR2 is populated. This is a SHORT command.
    "DGT_BUS_SEND_SNAPSHOT_F0":  CommandSpec(0xf0, 0xF0, b'\x7f'), # Sent after initial ledsOff().
    "DGT_BUS_SEND_SNAPSHOT_F4":  CommandSpec(0xf4, 0xF4, b'\x7f'), # Sent after F0 is called.
    "DGT_BUS_SEND_96":  CommandSpec(0x96, 0xb2), # Sent after F4 is called. This is a SHORT command.

    "DGT_BUS_SEND_STATE":     CommandSpec(0x82, 0x83, None),
    "DGT_BUS_SEND_CHANGES":   CommandSpec(0x83, 0x85, None),
    "DGT_SEND_BATTERY_INFO":  CommandSpec(0x98, 0xB5, None),
    "SOUND_GENERAL":          CommandSpec(0xb1, None, b'\x4c\x08'),
    "SOUND_FACTORY":          CommandSpec(0xb1, None, b'\x4c\x40'),
    "SOUND_POWER_OFF":        CommandSpec(0xb1, None, b'\x4c\x08\x48\x08'),
    "SOUND_POWER_ON":         CommandSpec(0xb1, None, b'\x48\x08\x4c\x08'),
    "SOUND_WRONG":            CommandSpec(0xb1, None, b'\x4e\x0c\x48\x10'),
    "SOUND_WRONG_MOVE":       CommandSpec(0xb1, None, b'\x48\x08'),
    "DGT_SLEEP":              CommandSpec(0xb2, 0xB1, b'\x0a'),
    "LED_OFF_CMD":            CommandSpec(0xb0, None, b'\x00'),
    "LED_FLASH_CMD":          CommandSpec(0xb0, None, b'\x05\x0a\x00\x01'),
    "DGT_NOTIFY_EVENTS":      CommandSpec(0x58, 0xa3, None),
    "DGT_RETURN_BUSADRES":    CommandSpec(0x46, 0x90, None),
    "DGT_SEND_TRADEMARK":     CommandSpec(0x97, 0xb4, None),
}

# Fast lookups
CMD_BY_NAME = {name: spec for name, spec in COMMANDS.items()}

# Export response-type constants (e.g., DGT_BUS_SEND_CHANGES_RESP)
globals().update({f"{name}_RESP": spec.expected_resp_type for name, spec in COMMANDS.items()})

# Export default data constants (e.g., DGT_BUS_SEND_CHANGES_DATA); value may be None
globals().update({f"{name}_DATA": spec.default_data for name, spec in COMMANDS.items()})

# Explicit definitions for linter (already exported above, but needed for static analysis)
DGT_BUS_SEND_CHANGES_RESP = COMMANDS["DGT_BUS_SEND_CHANGES"].expected_resp_type
DGT_BUS_SEND_STATE_RESP = COMMANDS["DGT_BUS_SEND_STATE"].expected_resp_type
DGT_NOTIFY_EVENTS_RESP = COMMANDS["DGT_NOTIFY_EVENTS"].expected_resp_type

# Export name namespace for commands, e.g. command.LED_OFF_CMD -> "LED_OFF_CMD"
command = SimpleNamespace(**{name: name for name in COMMANDS.keys()})

# Start-of-packet type bytes derived from registry (responses) + discovery types
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
    - FIFO request queue (blocks until previous request completes)
    - Same packet parsing and discovery as AsyncCentaur
    - Same unsolicited message handling
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
            developer_mode (bool): If True, use virtual serial ports via socat
            auto_init (bool): If True, initialize in background thread
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
        
        # Single waiter for blocking request_response
        self._waiter_lock = threading.Lock()
        self._response_waiter = None  # dict with keys: expected_type:int, queue:Queue
        
        # Request queue for FIFO serialization
        # Limit queue size to prevent unbounded memory growth
        self._request_queue = queue.Queue(maxsize=100)
        self._request_processor_thread = None
        
        # Piece event listener (marker 0x40/0x41 0..63, time_in_seconds)
        self._piece_listener = None
        
        # Dedicated worker for piece event callbacks
        try:
            self._callback_queue = queue.Queue(maxsize=256)
            self._callback_thread = threading.Thread(target=self._callback_worker, name="piece-callback", daemon=True)
            self._callback_thread.start()
        except Exception as e:
            log.error(f"[SyncCentaur] Failed to start callback worker: {e}")
            self._callback_queue = None
        
        if auto_init:
            init_thread = threading.Thread(target=self.run_background, daemon=False)
            init_thread.start()
    
    def run_background(self, start_key_polling=False):
        """Initialize in background thread"""
        self._closed = False
        self.listener_running = True
        self.ready = False
        self._initialize()
        
        # Start listener thread FIRST so it's ready to capture responses
        self.listener_thread = threading.Thread(target=self._listener_thread, daemon=True)
        self.listener_thread.start()
        
        # Start request processor thread
        self._request_processor_thread = threading.Thread(target=self._request_processor, daemon=True)
        self._request_processor_thread.start()
        
        # THEN send discovery commands
        log.info("Starting discovery...")
        self._discover_board_address()
    
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
            log.warning(f"Timeout waiting for SyncCentaur initialization (waited {timeout}s)")
        return self.ready
    
    def _initialize(self):
        """Open serial connection based on mode"""
        if self.developer_mode:
            log.debug("Developer mode enabled - setting up virtual serial port")
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
        
        log.info("Serial port opened successfully")
    
    def _listener_thread(self):
        """Continuously listen for data on the serial port"""
        log.info("Listening for serial data...")
        while self.listener_running:
            try:
                byte = self.ser.read(1)
                if not byte:
                    continue
                self.processResponse(byte[0])
            except Exception as e:
                log.error(f"Listener error: {e}")
    
    def processResponse(self, byte):
        """
        Process incoming byte - detect packet boundaries
        Supports two packet formats:
        
        Format 1 (old): [data...][addr1][addr2][checksum]
        Format 2 (new): [0x85][0x00][data...][addr1][addr2][checksum]
        
        Both have [addr1][addr2][checksum] pattern at the end.
        """
        self._handle_orphaned_data_detection(byte)
        self.response_buffer.append(byte)
        
        # Try special handlers first
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
                            log.warning(f"[ORPHANED] {hex_row}")
                            self.response_buffer = bytearray(self.response_buffer[-(HEADER_DATA_BYTES):])
                            log.info(f"After trimming: self.response_buffer: {self.response_buffer}")
    
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
                        self.on_packet_complete(self.response_buffer)
                        return True
                    else:
                        if self.response_buffer[0] == DGT_NOTIFY_EVENTS_RESP:
                            log.info(f"DGT_NOTIFY_EVENTS_RESP: {' '.join(f'{b:02x}' for b in self.response_buffer)}")
                            self.handle_key_payload(self.response_buffer[1:])
                            self.response_buffer = bytearray()
                            self.packet_count += 1
                            return True
                        else:
                            log.info(f"checksum mismatch: {' '.join(f'{b:02x}' for b in self.response_buffer)}")
                            self.response_buffer = bytearray()
                            return False
                else:
                    # Short packet
                    self.on_packet_complete(self.response_buffer)
                    return True
        return False
    
    def on_packet_complete(self, packet):
        """Called when complete packet received"""
        self.response_buffer = bytearray()
        self.packet_count += 1
        
        #try:
        truncated_packet = packet[:50]
        log.info(f"[P{self.packet_count:03d}] on_packet_complete: {' '.join(f'{b:02x}' for b in truncated_packet)}")
        # Handle discovery or route to handler
        if not self.ready:
            self._discover_board_address(packet)
            return
        
        # Try delivering to waiter first
        if self._try_deliver_to_waiter(packet):
            return
        
        self._route_packet_to_handler(packet)
        # finally:
        #     if packet[0] == DGT_PIECE_EVENT_RESP:
        #         self.sendPacket(command.DGT_BUS_SEND_CHANGES)
        #     else:
        #         self.sendPacket(command.DGT_NOTIFY_EVENTS)
    
    def _try_deliver_to_waiter(self, packet):
        """Try to deliver packet to waiting request, returns True if delivered"""
        try:
            with self._waiter_lock:
                if self._response_waiter is not None:
                    expected_type = self._response_waiter.get('expected_type')
                    if expected_type == packet[0]:
                        payload = self._extract_payload(packet)
                        q = self._response_waiter.get('queue')
                        self._response_waiter = None
                        if q is not None:
                            try:
                                q.put_nowait(payload)
                            except Exception:
                                pass
                            return True
        except Exception:
            pass
        return False
    
    def _route_packet_to_handler(self, packet):
        """Route packet to appropriate handler based on type"""
        try:
            payload = self._extract_payload(packet)
            if packet[0] == DGT_BUS_SEND_CHANGES_RESP:
                self.handle_board_payload(payload)
            elif packet[0] == DGT_PIECE_EVENT_RESP:
                log.debug(f"Piece event detected (0x8e), waiting for DGT_BUS_SEND_CHANGES response")
            elif packet[0] == DGT_BUS_SEND_STATE_RESP:
                log.debug(f"Unsolicited board state packet (0x83) - no active waiter")
            else:
                log.info(f"Unknown packet type: {' '.join(f'{b:02x}' for b in packet)}")
        except Exception as e:
            log.error(f"Error: {e}")
    
    def handle_board_payload(self, payload: bytes):
        """Handle piece movement events from board payload"""
        try:
            if len(payload) > 0:
                
                time_in_seconds = time_utils.decode_time(payload)
                time_str = f"  [TIME: {time_utils.format_time_display(time_in_seconds)}]"
                hex_row = ' '.join(f'{b:02x}' for b in payload)
                log.info(f"[P{self.packet_count:03d}] {hex_row}{time_str}")
                self._draw_piece_events_from_payload(payload)
                # Dispatch to registered listeners with parsed events
                try:
                    i = 0
                    while i < len(payload) - 1:
                        piece_event = payload[i]
                        if piece_event in (0x40, 0x41):
                            piece_event = 0 if piece_event == 0x40 else 1
                            field_hex = payload[i + 1]
                            try:
                                log.info(f"[P{self.packet_count:03d}] piece_event={piece_event == 0 and 'LIFT' or 'PLACE'} field_hex={field_hex} time_in_seconds={time_in_seconds} {time_str}")
                                if self._piece_listener is not None:
                                    args = (piece_event, field_hex, time_in_seconds)
                                    cq = getattr(self, '_callback_queue', None)
                                    if cq is not None:
                                        try:
                                            cq.put_nowait((self._piece_listener, args))
                                        except queue.Full:
                                            log.error("[SyncCentaur] callback queue full, dropping piece event")
                                    else:
                                        self._piece_listener(*args)
                            except Exception as e:
                                log.error(f"Error processing piece event: {e}")
                                import traceback
                                traceback.print_exc()
                            i += 2
                        else:
                            i += 1
                except Exception as e:
                    log.error(f"Error in handle_board_payload: {e}")
                    import traceback
                    traceback.print_exc()
        except Exception as e:
            log.error(f"Error: {e}")
    
    def handle_key_payload(self, payload: bytes):
        """Handle key press events"""
        try:
            log.info(f"[P{self.packet_count:03d}] handle_key_payload: {' '.join(f'{b:02x}' for b in payload)}")
            if len(payload) > 0:
                hex_row = ' '.join(f'{b:02x}' for b in payload)
                log.info(f"[P{self.packet_count:03d}] {hex_row}")
                idx, code_val, is_down = self._find_key_event_in_payload(payload)
                if idx is not None:
                    self._draw_key_event_from_payload(payload, idx, code_val, is_down)
                    if not is_down:
                        key = Key(code_val)
                        log.info(f"key name: {key.name} value: {key.value}")
                        self._last_key = key
                        try:
                            self.key_up_queue.put_nowait(key)
                        except queue.Full:
                            pass
                else:
                    log.info(f"No key event found in payload: {' '.join(f'{b:02x}' for b in payload)}")
        except Exception as e:
            log.error(f"Error: {e}")
    
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
                    log.error(f"[SyncCentaur] piece callback error: {e}")
            except Exception as e:
                log.error(f"[SyncCentaur] callback worker loop error: {e}")
    
    def _request_processor(self):
        """Process requests from FIFO queue"""
        while self.listener_running:
            try:
                request = self._request_queue.get(timeout=0.1)
                if request is None:
                    continue
                
                command_name, data, timeout, result_queue = request
                
                try:
                    payload = self._execute_request(command_name, data, timeout)
                    result_queue.put(('success', payload))
                except Exception as e:
                    result_queue.put(('error', e))
            except queue.Empty:
                continue
            except Exception as e:
                log.error(f"Request processor error: {e}")
    
    def _execute_request(self, command_name: str, data: Optional[bytes], timeout: float):
        """Execute a single request synchronously"""
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)
        expected_type = spec.expected_resp_type
        
        # If no response expected, just send and return
        if expected_type is None:
            self.sendPacket(command_name, eff_data)
            return b''
        
        # Create waiter
        result_queue = queue.Queue(maxsize=1)
        with self._waiter_lock:
            if self._response_waiter is not None:
                log.warning("Warning: waiter still set")
                self._response_waiter = None
            self._response_waiter = {'expected_type': expected_type, 'queue': result_queue}
        
        # Send command
        self.sendPacket(command_name, eff_data)
        
        # Wait for response
        try:
            payload = result_queue.get(timeout=timeout)
            return payload
        except queue.Empty:
            # Timeout
            with self._waiter_lock:
                if self._response_waiter is not None and self._response_waiter.get('queue') is result_queue:
                    self._response_waiter = None
            log.info(f"Request timeout for {command_name}")
            return None
    
    def request_response(self, command_name: str, data: Optional[bytes]=None, timeout=10.0, callback=None, raw_len: Optional[int]=None, retries=0):
        """
        Send a command and wait for response (blocking, FIFO queued).
        
        Args:
            command_name: command name to send
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
            log.error(f"Request queue timeout for {command_name}")
            return None
    
    def wait_for_key_up(self, timeout=None, accept=None):
        """Block until a key-up event is received"""
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
        """Non-blocking: return the last key-up event and reset it"""
        last_key = self._last_key
        self._last_key = None
        return last_key
    
    def sendPacket(self, command_name: str, data: Optional[bytes] = None):
        """
        Send a packet to the board using a command name.
        
        Args:
            command_name: command name in COMMANDS (e.g., "LED_OFF_CMD")
            data: bytes for data payload; if None, use default_data from the named command if available
        """
        if not isinstance(command_name, str):
            raise TypeError("sendPacket requires a command name (str), e.g. command.LED_OFF_CMD")
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)
        tosend = self.buildPacket(spec.cmd, eff_data)
        log.info(f"sendPacket: {command_name} ({spec.cmd:02x}) {' '.join(f'{b:02x}' for b in tosend[:16])}")
        self.ser.write(tosend)
        #if self.ready and spec.expected_resp_type is None and command_name != command.DGT_NOTIFY_EVENTS:
        #    self.sendPacket(command.DGT_NOTIFY_EVENTS)
    
    def buildPacket(self, command, data):
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
        barr_csum = (csum % 128)
        return barr_csum
    
    def _extract_payload(self, packet):
        """Extract full payload bytes from a complete packet"""
        if not packet or len(packet) < 6:
            return b''
        return bytes(packet[5:len(packet)-1])
    
    def _discover_board_address(self, packet=None):
        """
        Self-contained state machine for non-blocking board discovery.
        
        Args:
            packet: Complete packet bytearray (from processResponse)
                    None when called from run_background()
        """
        if self.ready:
            return
        
        # Called from run_background() with no packet
        if packet is None:
            log.info("Discovery: STARTING")
            self.ser.write(0x4d)
            self.ser.write(0x4e)
            self.sendPacket(command.DGT_BUS_SEND_87)
            #self.sendPacket(command.DGT_RETURN_BUSADRES)
            return
        
        log.info(f"Discovery: packet: {' '.join(f'{b:02x}' for b in packet)}")
        # Called from processResponse() with a complete packet
        if packet[0] == 0x87:
            if self.addr1 == 0x00 and self.addr2 == 0x00:
                self.sendPacket(command.DGT_BUS_SEND_87)
                self.addr1 = packet[3]
                self.addr2 = packet[4]
            else:
                if self.addr1 == packet[3] and self.addr2 == packet[4]:
                    self.ready = True
                    #self.sendPacket(command.DGT_NOTIFY_EVENTS)
                    log.info(f"Discovery: READY - addr1={hex(self.addr1)}, addr2={hex(self.addr2)}")
                    self.ledsOff()
                    self.beep(command.SOUND_POWER_ON)
                else:
                    log.info(f"Discovery: ERROR - addr1={hex(self.addr1)}, addr2={hex(self.addr2)} does not match packet {packet[3]} {packet[4]}")
                    self.addr1 = 0x00
                    self.addr2 = 0x00
                    log.info("Discovery: RETRY")
                    self.sendPacket(command.DGT_BUS_SEND_87)
                    return
    
    def cleanup(self, leds_off: bool = True):
        """Idempotent cleanup coordinator"""
        if getattr(self, "_closed", False):
            return
        self._cleanup_listener()
        if leds_off:
            self._cleanup_leds()
        self._cleanup_waiters()
        self._cleanup_serial()
        self._closed = True
        log.info("SyncCentaur cleaned up")
    
    def _cleanup_listener(self):
        """Stop and join listener thread"""
        try:
            self.listener_running = False
            t = getattr(self, "listener_thread", None)
            if t and t.is_alive():
                t.join(timeout=1.0)
        except Exception:
            pass
    
    def _cleanup_leds(self):
        """Turn off LEDs"""
        try:
            self.ledsOff()
        except Exception:
            pass
    
    def _cleanup_waiters(self):
        """Clear outstanding waiters"""
        try:
            with self._waiter_lock:
                self._response_waiter = None
        except Exception:
            pass
    
    def _cleanup_serial(self):
        """Clear buffers and close serial port"""
        try:
            log.info(f"Clearing response buffer in _cleanup_serial")
            self.response_buffer = bytearray()
        except Exception:
            pass
        try:
            if self.ser:
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    try:
                        n = getattr(self.ser, 'in_waiting', 0) or 0
                        if n:
                            self.ser.read(n)
                    except Exception:
                        try:
                            self.ser.read(10000)
                        except Exception:
                            pass
        except Exception:
            pass
        
        self.ready = False
        try:
            if self.ser:
                self.ser.close()
                self.ser = None
                log.info("Serial port closed")
        except Exception:
            pass
        
        self._last_key = None
    
    def beep(self, sound_name: str):
        self.sendPacket(sound_name)
    
    def ledsOff(self):
        self.sendPacket(command.LED_OFF_CMD)
    
    def ledArray(self, inarray, speed=3, intensity=5):
        data = bytearray([0x05])
        data.append(speed)
        data.append(0)
        data.append(intensity)
        for i in range(0, len(inarray)):
            data.append(inarray[i])
        self.sendPacket(command.LED_FLASH_CMD, data)
    
    def ledFromTo(self, lfrom, lto, intensity=5):
        data = bytearray([0x05, 0x03, 0x00])
        data.append(intensity)
        data.append(lfrom)
        data.append(lto)
        self.sendPacket(command.LED_FLASH_CMD, data)
    
    def led(self, num, intensity=5):
        data = bytearray([0x05, 0x0a, 0x01])
        data.append(intensity)
        data.append(num)
        self.sendPacket(command.LED_FLASH_CMD, data)
    
    def ledFlash(self):
        self.sendPacket(command.LED_FLASH_CMD)
    
    def sleep(self):
        """Sleep the controller"""
        log.info(f"sleep")
        self.sendPacket(command.DGT_SLEEP)
            
    def _draw_piece_events_from_payload(self, payload: bytes):
        """Print a compact list of piece events extracted from the payload"""
        try:
            events = []
            i = 0
            while i < len(payload) - 1:
                marker = payload[i]
                if marker in (0x40, 0x41):
                    field_hex = payload[i + 1]
                    arrow = "↑" if marker == 0x40 else "↓"
                    events.append(f"{arrow} {field_hex:02x}")
                    i += 2
                else:
                    i += 1
            if events:
                prefix = f"[P{self.packet_count:03d}] "
                log.info(prefix + " ".join(events))
        except Exception as e:
            log.error(f"Error in _draw_piece_events_from_payload: {e}")
    
    def _find_key_event_in_payload(self, payload: bytes):
        """Detect a key event within a key payload"""
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
    
    def _draw_key_event_from_payload(self, payload: bytes, code_index: int, code_val: int, is_down: bool):
        """Print a single-line key event indicator"""
        base_name = DGT_BUTTON_CODES.get(code_val, f"0x{code_val:02x}")
        prefix = f"[P{self.packet_count:03d}] "
        log.info(prefix + f"{base_name} {'↓' if is_down else '↑'}")
        return True
