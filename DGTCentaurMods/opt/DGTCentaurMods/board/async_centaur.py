# DGT Centaur Asynchronous Board Controller
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# AsyncCentaur (async_centaur.py) was written by Adrian Dybwad 
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
import itertools
from dataclasses import dataclass
from typing import Dict, Optional
from types import SimpleNamespace

try:
    logging.basicConfig(level=logging.DEBUG, filename="/home/pi/debug.log", filemode="w")
except:
    logging.basicConfig(level=logging.DEBUG)


"""
DGT Centaur Serial Protocol - Packet Structure

All packets follow this structure:
    <type1> <type2> <length> <addr1> <addr2> [time_signals...] [data...] <checksum>

Where:
    type1, type2 (bytes 0-1): Protocol type identifier, typically 0x85 0x00 for new format
    length (byte 2): Total packet length in bytes, including all fields up to and including checksum
    addr1 (byte 3): Board address 1 (e.g., 0x06)
    addr2 (byte 4): Board address 2 (e.g., 0x50)
    time_signals (bytes 5 to n): Clock time (only present when piece events occur)
        Format: [.ss] [ss] [mm] [hh]
        - Byte 0: Subseconds (0x00-0xFF = 0.00-0.99)
        - Byte 1: Seconds (optional, 0-59, only present if subseconds are > 9.99)
        - Byte 2: Minutes (optional, 0-59, only present if seconds are > 59)
        - Byte 3: Hours (optional, for times > 59:59)
        - Variable length: 1-4 bytes depending on time range (there may be more, but implemented only 4 bytes)
        - Display: "M:SS.XX" or "H:MM:SS.XX"
    data (bytes after time to n-1): Variable-length payload (piece events, etc.)
        - 0x40: Piece lifted (followed by square hex value)
        - 0x41: Piece placed (followed by square hex value)
    checksum (byte n): Last byte = sum of all previous bytes mod 128

Examples:
    "No piece" response: 85 00 06 06 50 61
        - Length = 6 bytes (entire packet)
        - No time signals, no data payload
        - Checksum: (0x85 + 0x00 + 0x06 + 0x06 + 0x50) % 128 = 0x61
    
    Piece event with time: 85 00 0a 06 50 18 0c 40 30 79
        - Length = 10 bytes
        - Time = 18 0c (0.09s + 12s = 12.09s)
        - Data = 40 30 (lift at square 0x30)
        - Checksum: validates complete packet
    
    Multi-move game moment: 85 00 22 06 50 2a 03 05 41 30 09...
        - Length = 34 bytes
        - Time = 2a 03 05 (42.16s + 3s + 5min = 5:03.42)
        - Data = multiple lift/place events

Parsing Algorithm:
    1. Accumulate bytes into a buffer
    2. For each new byte, calculate checksum of all previous bytes (mod 128)
    3. If incoming byte equals that checksum:
        a. Extract length from buffer[2]
        b. If len(buffer) == declared_length: valid packet found, emit it
        c. Otherwise: false positive, continue accumulating
    4. When 0x85 0x00 sequence detected while buffer has data: log as orphaned, discard
    5. During discovery (STARTING/INITIALIZING/AWAITING_PACKET states): pass to state machine
    6. Once READY: process as normal game packets
"""

 # response header constants not needed; use exported *_RESP values

# Unified command registry
@dataclass(frozen=True)
class CommandSpec:
    cmd: bytes
    expected_resp_type: int
    default_data: Optional[bytes] = None

COMMANDS: Dict[str, CommandSpec] = {
    "DGT_BUS_SEND_STATE":  CommandSpec(0x42, 0x86, b'\x7f'),
    "DGT_BUS_SEND_SNAPSHOT":  CommandSpec(0xf0, 0xF0, b'\x7f'),
    "DGT_DISCOVERY_REQ":      CommandSpec(0x46, 0x93, None),
    "DGT_DISCOVERY_ACK":      CommandSpec(0x87, 0x87, None),
    "DGT_BUS_SEND_CHANGES":   CommandSpec(0x83, 0x85, None),
    "DGT_BUS_POLL_KEYS":      CommandSpec(0x94, 0xB1, None),
    "DGT_SEND_BATTERY_INFO":  CommandSpec(0x98, 0xB5, None),
    "SOUND_GENERAL":          CommandSpec(0xb1, 0xB1, b'\x4c\x08'),
    "SOUND_FACTORY":          CommandSpec(0xb1, 0xB1, b'\x4c\x40'),
    "SOUND_POWER_OFF":        CommandSpec(0xb1, 0xB1, b'\x4c\x08\x48\x08'),
    "SOUND_POWER_ON":         CommandSpec(0xb1, 0xB1, b'\x48\x08\x4c\x08'),
    "SOUND_WRONG":            CommandSpec(0xb1, 0xB1, b'\x4e\x0c\x48\x10'),
    "SOUND_WRONG_MOVE":       CommandSpec(0xb1, 0xB1, b'\x48\x08'),
    "DGT_SLEEP":              CommandSpec(0xb2, 0xB1, b'\x0a'),

    "LED_OFF_CMD":            CommandSpec(0xb0, 0xB1, b'\x00'),
    "LED_FLASH_CMD":          CommandSpec(0xb0, 0xB1, b'\x05\x0a\x00\x01'),

    "DISC_1":  CommandSpec(0x4d, 0xb1, None),
    "DISC_2":  CommandSpec(0x4e, 0x93, None),
    # Returns the addr1 and addr2 values. If current addr1 and addr2 = 0x00, 
    # then response is 0x90 packet twice
    "DGT_RETURN_BUSADRES":    CommandSpec(0x46, 0x90, None),
    # Returns the trademark
    "DGT_SEND_TRADEMARK":     CommandSpec(0x47, 0x92, None),

    # Changes the addr1 and addr2 values, no response
    "DGT_BUS_RANDOMIZE_PIN":  CommandSpec(0x92, None, None),

    "DGT_SEND_UPDATE":        CommandSpec(0x43, None, None), # Will cause unsolicited packets with 8e message type till 83 is called.
    "DGT_SEND_UPDATE_BRD":    CommandSpec(0x44, None, None), # Will cause unsolicited packets with 8e message type till 83 is called.

}


# Fast lookups (name-only API)
CMD_BY_NAME = {name: spec for name, spec in COMMANDS.items()}
RESP_TYPE_TO_SPEC = {spec.expected_resp_type: spec for spec in COMMANDS.values()}

# Export response-type constants (e.g., DGT_BUS_SEND_CHANGES_RESP)
globals().update({f"{name}_RESP": spec.expected_resp_type for name, spec in COMMANDS.items()})

# Export default data constants (e.g., DGT_BUS_SEND_CHANGES_DATA); value may be None
globals().update({f"{name}_DATA": spec.default_data for name, spec in COMMANDS.items()})

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
# Convenient maps
KEY_NAME_BY_CODE = dict(DGT_BUTTON_CODES)                 # {0x01: 'BACK', 0x10: 'TICK', ...}
KEY_CODE_BY_NAME = {v: k for k, v in KEY_NAME_BY_CODE.items()}  # {'BACK': 0x01, 'TICK': 0x10, ...}

# Typed enum using the raw controller codes as values
Key = IntEnum('Key', {name: code for name, code in KEY_CODE_BY_NAME.items()})


__all__ = ['AsyncCentaur', 'DGT_BUS_SEND_CHANGES', 'DGT_BUS_POLL_KEYS', 'DGT_SEND_BATTERY_INFO', 'DGT_BUTTON_CODES', 'command']

class AsyncCentaur:
    """DGT Centaur Asynchronous Board Controller

    Overview:
        AsyncCentaur manages serial communication with the DGT Centaur in a
        background thread, handling discovery, packet parsing, and a simple
        request/response API (blocking or callback-based).

    Quick start:
        centaur = AsyncCentaur(developer_mode=False)
        centaur.wait_ready()
        # Blocking request (returns payload bytes)
        payload = centaur.request_response(DGT_BUS_SEND_CHANGES, timeout=1.5)

    Non-blocking:
        def on_resp(payload, err):
            if err:
                print(err)
            else:
                print(payload)
        centaur.request_response(DGT_BUS_POLL_KEYS, timeout=1.5, callback=on_resp)

    Key APIs:
        - run_background(start_key_polling=False): init and start listener
        - wait_ready(timeout=60): wait for discovery
        - request_response(command, data=b"", timeout=2.0, callback=None)
        - wait_for_key_up(timeout=None, accept=None)
        - get_and_reset_last_key()
        - ledsOff(), led(), ledArray(), ledFromTo(), beep(), sleep()

    Notes:
    - Commands are defined in COMMANDS; exported byte constants are available
      (e.g., DGT_BUS_SEND_CHANGES, DGT_BUS_POLL_KEYS, DGT_SEND_BATTERY_INFO).
        - Payload is bytes after addr2 up to (excluding) checksum → packet[5:-1].
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
        self.packet_count = 0
        self._closed = False
        # queue to signal key-up events as (code, name)
        self.key_up_queue = queue.Queue(maxsize=128)
        # track last key-up (code, name) for non-blocking retrieval
        self._last_key = None
        # single waiter for blocking request_response
        self._waiter_lock = threading.Lock()
        self._response_waiter = None  # dict with keys: expected_type:int, queue:Queue
        self._request_lock = threading.Lock()  # Serialize blocking requests

        # raw byte capture waiter (bypasses checksum/length parsing)
        self._raw_waiter_lock = threading.Lock()
        self._raw_waiter = None  # {'target_len': int, 'buf': bytearray, 'queue': Queue, 'callback': Optional[Callable]}

        # Piece event listener (marker 0x40/0x41, square 0..63, time_in_seconds)
        self._piece_listener = None

        if auto_init:
            init_thread = threading.Thread(target=self.run_background, daemon=False)
            init_thread.start()

        # Dedicated worker for piece event callbacks to avoid blocking serial listener
        try:
            self._callback_queue = queue.Queue(maxsize=256)
            self._callback_thread = threading.Thread(target=self._callback_worker, name="piece-callback", daemon=True)
            self._callback_thread.start()
        except Exception as e:
            # Fallback: if thread creation fails, leave queue uninitialized
            print(f"[AsyncCentaur] Failed to start callback worker: {e}")
            self._callback_queue = None

    
    def run_background(self, start_key_polling=False):
        """Initialize in background thread"""
        self.listener_running = True
        self.ready = False
        self._initialize()
        
        # Start listener thread FIRST so it's ready to capture responses
        self.listener_thread = threading.Thread(target=self._listener_thread, daemon=True)
        self.listener_thread.start()

        # THEN send discovery commands
        print("Starting discovery...")
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
            logging.warning(f"Timeout waiting for AsyncCentaur initialization (waited {timeout}s)")
        return self.ready
    
    def _listener_thread(self):
        """Continuously listen for data on the serial port and print it"""
        print("Listening for serial data (press Ctrl+C to stop)...")
        while self.listener_running:
            try:
                byte = self.ser.read(1)
                if not byte:
                    continue

                # if 32 <= byte[0] < 127:
                #     print(f"RCVD: {byte[0]:02x} {chr(byte[0])}")
                # else:
                #     print(f"RCVD: {byte[0]:02x} (CTL)")


                # RAW CAPTURE: divert bytes to raw buffer if active
                raw_to_deliver = None
                with self._raw_waiter_lock:
                    if self._raw_waiter is not None:
                        self._raw_waiter['buf'].append(byte[0])
                        if len(self._raw_waiter['buf']) >= self._raw_waiter['target_len']:
                            raw_bytes = bytes(self._raw_waiter['buf'])
                            cb = self._raw_waiter.get('callback')
                            q = self._raw_waiter.get('queue')
                            self._raw_waiter = None
                            if cb is not None:
                                def _dispatch():
                                    try:
                                        cb(raw_bytes, None)
                                    except Exception:
                                        pass
                                threading.Thread(target=_dispatch, daemon=True).start()
                            else:
                                raw_to_deliver = (q, raw_bytes)
                        # Always consume while raw capture is active
                        if raw_to_deliver is None:
                            continue

                if raw_to_deliver is not None:
                    q, raw_bytes = raw_to_deliver
                    try:
                        q.put_nowait(raw_bytes)
                    except Exception:
                        pass
                    continue

                # Normal parsing path
                self.processResponse(byte[0])
            except Exception as e:
                logging.error(f"Listener error: {e}")

    def _callback_worker(self):
        """Run piece-event callbacks off the serial thread to allow blocking calls inside callbacks."""
        while True:
            try:
                item = self._callback_queue.get()
                if not item:
                    continue
                fn, args = item
                try:
                    fn(*args)
                except Exception as e:
                    print(f"[AsyncCentaur] piece callback error: {e}")
            except Exception as e:
                # Keep worker alive even on unexpected errors
                print(f"[AsyncCentaur] callback worker loop error: {e}")
    
    def stop_listener(self):
        """Stop the serial listener thread"""
        self.listener_running = False
        print("Serial listener thread stopped")
    
    def _initialize(self):
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
        
        print("Serial port opened successfully")
    

    def processResponse(self, byte):
        """
        Process incoming byte - detect packet boundaries
        Supports two packet formats:
        
        Format 1 (old): [data...][addr1][addr2][checksum]
        Format 2 (new): [0x85][0x00][data...][addr1][addr2][checksum]
        
        Both have [addr1][addr2][checksum] pattern at the end.
        Packet boundary is detected when:
        1. Buffer ends with valid [addr1][addr2][checksum], OR
        2. A new 85 00 header is detected (indicating start of next packet)
        """
        self._handle_orphaned_data_detection(byte)
        self.response_buffer.append(byte)
        
        # Try special handlers first
        if not self.ready and self._try_discovery_packet_detection():
            return
        if self._try_checksum_packet_detection(byte):
            return
        
        # Prevent buffer overflow
        if len(self.response_buffer) > 1000:
            self.response_buffer.pop(0)

    def _handle_orphaned_data_detection(self, byte):
        """Detect and log orphaned data when new packet starts"""
        # Detect packet start sequence (<START_TYPE_BYTE> 00) while buffer has data
        HEADER_DATA_BYTES = 4
        if len(self.response_buffer) >= HEADER_DATA_BYTES:
            if self.response_buffer[-HEADER_DATA_BYTES] in START_TYPE_BYTES:
                if self.response_buffer[-HEADER_DATA_BYTES+3] == self.addr1:
                    if byte == self.addr2: 
                        if len(self.response_buffer) > HEADER_DATA_BYTES:
                            # Log orphaned data (everything except the 85)
                            hex_row = ' '.join(f'{b:02x}' for b in self.response_buffer[:-1])
                            print(f"[ORPHANED] {hex_row}")
                            self.response_buffer = bytearray(self.response_buffer[-(HEADER_DATA_BYTES):])  # last 5 bytes
                            print(f"After trimming: self.response_buffer: {self.response_buffer}")

    def _try_discovery_packet_detection(self):
        """Handle 0x93 packets without checksum, returns True if packet complete"""
        # Special handling for 0x93 discovery packets (no checksum, use declared length)
        if not self.ready and len(self.response_buffer) >= 3:
            if self.response_buffer[0] == 0x90:
                len_hi, len_lo = self.response_buffer[1], self.response_buffer[2]
                declared_length = ((len_hi & 0x7F) << 7) | (len_lo & 0x7F)
                if len(self.response_buffer) == declared_length:
                    # Complete 0x93 packet received
                    self.on_packet_complete(self.response_buffer)
                    self.response_buffer = bytearray()
                    return True
        return False

    def _try_checksum_packet_detection(self, byte):
        """Handle checksum-validated packets, returns True if packet complete"""
        # Check if this byte is a checksum boundary
        if len(self.response_buffer) >= 2:
            calculated_checksum = self.checksum(self.response_buffer[:-1])
            if byte == calculated_checksum:
                # Verify packet length matches declared length
                if len(self.response_buffer) >= 6:
                    len_hi, len_lo = self.response_buffer[1], self.response_buffer[2]
                    declared_length = ((len_hi & 0x7F) << 7) | (len_lo & 0x7F)
                    actual_length = len(self.response_buffer)
                    if actual_length == declared_length:
                        # We have a valid packet
                        self.on_packet_complete(self.response_buffer)
                        self.response_buffer = bytearray()
                        return True
                else:
                    self.on_packet_complete(self.response_buffer)
                    self.response_buffer = bytearray()
                    return True
        return False
    
    def on_packet_complete(self, packet):
        """Called when complete packet received"""
        self.packet_count += 1
        
        # Try delivering to waiter first
        if self._try_deliver_to_waiter(packet):
            return
        
        # Handle discovery or route to handler
        if not self.ready:
            self._discover_board_address(packet)
            return
        
        self._route_packet_to_handler(packet)

    def _try_deliver_to_waiter(self, packet):
        """Try to deliver packet to waiting request, returns True if delivered"""
        # Deliver to blocking/non-blocking waiter first (if any)
        try:
            with self._waiter_lock:
                if self._response_waiter is not None:
                    expected_type = self._response_waiter.get('expected_type')
                    #print(f"exp={expected_type!r} {type(expected_type)}, got={packet[0]!r} {type(packet[0])}")
                    if expected_type == packet[0]:
                        #print(f"Matching packet type: {expected_type} == {packet[0]}")
                        payload = self._extract_payload(packet)
                        cb = self._response_waiter.get('callback') if isinstance(self._response_waiter, dict) else None
                        q = self._response_waiter.get('queue') if isinstance(self._response_waiter, dict) else None
                        t = self._response_waiter.get('timer') if isinstance(self._response_waiter, dict) else None
                        if t is not None:
                            try:
                                t.cancel()
                            except Exception:
                                pass
                        # clear waiter before dispatch to avoid races
                        self._response_waiter = None
                        if cb is not None:
                            def _dispatch():
                                try:
                                    cb(payload, None)
                                except Exception:
                                    pass
                            threading.Thread(target=_dispatch, daemon=True).start()
                            return True
                        else:
                            try:
                                q.put_nowait(payload)
                            except Exception:
                                pass
                            return True
        except Exception:
            # Do not break normal flow on waiter issues
            pass
        return False

    def _route_packet_to_handler(self, packet):
        """Route packet to appropriate handler based on type"""
        try:
            payload = self._extract_payload(packet)
            if packet[0] == DGT_BUS_SEND_CHANGES_RESP:
                self.handle_board_payload(payload)
            elif packet[0] == DGT_BUS_POLL_KEYS_RESP:
                self.handle_key_payload(payload)
            else:
                print(f"Unknown packet type: {packet[0]} {packet}")
        except Exception as e:
            print(f"Error: {e}")
            return
        
        # Request next packet if ready
        if self.ready:
            print(f"\r{next(self.spinner)}", end='', flush=True)

    def handle_board_payload(self, payload: bytes):
        try:
            if len(payload) > 0:
                # time bytes are before first event marker
                time_bytes = self._extract_time_from_payload(payload)
                time_str = ""
                if time_bytes:
                    time_formatted = self._format_time_display(time_bytes)
                    if time_formatted:
                        time_str = f"  [TIME: {time_formatted}]"
                hex_row = ' '.join(f'{b:02x}' for b in payload)
                print(f"\r[P{self.packet_count:03d}] {hex_row}{time_str}")
                self._draw_piece_events_from_payload(payload)

                # Dispatch to registered listeners with parsed events
                try:
                    i = 0
                    while i < len(payload) - 1:
                        piece_event = payload[i]
                        if piece_event in (0x40, 0x41):
                            # 0 is lift, 1 is place
                            piece_event = 0 if piece_event == 0x40 else 1
                            field_hex = payload[i + 1]
                            try:
                                # The leds use this format to address the square
                                square = self.rotateFieldHex(field_hex)
                                print(f"[P{self.packet_count:03d}] piece_event={piece_event == 0 and 'LIFT' or 'PLACE'} field_hex={field_hex} square={square} time_in_seconds={self._get_seconds_from_time_bytes(time_bytes)}")
                                if self._piece_listener is not None:
                                    args = (piece_event, field_hex, square, self._get_seconds_from_time_bytes(time_bytes))
                                    cq = getattr(self, '_callback_queue', None)
                                    if cq is not None:
                                        try:
                                            cq.put_nowait((self._piece_listener, args))
                                        except queue.Full:
                                            # Drop if overwhelmed to avoid blocking serial listener
                                            print("[AsyncCentaur] callback queue full, dropping piece event")
                                    else:
                                        # Fallback invoke inline if queue unavailable
                                        self._piece_listener(*args)
                                else:
                                    print(f"No piece listener registered to handle event")
                            except Exception as e:
                                print(f"Error in _draw_piece_events_from_payload: {e}")
                                import traceback
                                traceback.print_exc()
                            i += 2
                        else:
                            i += 1
                except Exception as e:
                    print(f"Error in _draw_piece_events_from_payload: {e}")
                    import traceback
                    traceback.print_exc()

            self.sendPacket(command.DGT_BUS_SEND_CHANGES)
        except Exception as e:
            print(f"Error: {e}")
            return 

    def handle_key_payload(self, payload: bytes):
        try:
            if len(payload) > 0:
                hex_row = ' '.join(f'{b:02x}' for b in payload)
                print(f"\r[P{self.packet_count:03d}] {hex_row}")
                idx, code_val, is_down = self._find_key_event_in_payload(payload)
                if idx is not None:
                    self._draw_key_event_from_payload(payload, idx, code_val, is_down)
                    if not is_down:
                        name = DGT_BUTTON_CODES.get(code_val, f"0x{code_val:02x}")
                        key = Key(code_val)
                        print(f"key: {key}")
                        print(f"key name: {key.name}")
                        print(f"key value: {key.value}")
                        self._last_key = key
                        try:
                            self.key_up_queue.put_nowait(key)
                        except queue.Full:
                            pass

            self.sendPacket(command.DGT_BUS_POLL_KEYS)
        except Exception as e:
            print(f"Error: {e}")
            return 

    def _extract_time_from_payload(self, payload: bytes) -> bytes:
        """
        Return the time bytes prefix from a board payload.

        The board payload layout is:
            [optional time bytes ...] [events ...]
        where events are pairs of bytes starting with 0x40 (lift) or 0x41 (place),
        followed by the field hex. This function returns all bytes before the
        first event marker (0x40/0x41). If no markers are present, the entire
        payload is treated as time bytes; if the payload is empty, returns b"".
        """
        out = bytearray()
        for b in payload:
            if b in (0x40, 0x41):
                break
            out.append(b)
        return bytes(out)

    def _get_seconds_from_time_bytes(self, time_bytes):
        """
        Return the seconds from the time bytes.
        """
        if len(time_bytes) == 0:
            return 0
        # TODO: It should be confirmed that we see all values up to 265 in position 0
        time_in_seconds = time_bytes[0] / 256.0
        time_in_seconds += time_bytes[1] if len(time_bytes) >  1 else 0
        time_in_seconds += time_bytes[2] * 60 if len(time_bytes) > 2 else 0
        time_in_seconds += time_bytes[3] * 3600 if len(time_bytes) > 3 else 0

        return time_in_seconds
            
    def _format_time_display(self, time_bytes):
        """
        Format time bytes as human-readable time string.
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
        if len(time_bytes) == 0:
            return ""
        
        subsec = time_bytes[0] if len(time_bytes) > 0 else 0
        seconds = time_bytes[1] if len(time_bytes) > 1 else 0
        minutes = time_bytes[2] if len(time_bytes) > 2 else 0
        hours = time_bytes[3] if len(time_bytes) > 3 else 0
        if len(time_bytes) > 4:
            print(f"Warning: time_bytes has more than 4 bytes: {time_bytes}")
        
        # Convert subsec to hundredths
        subsec_decimal = subsec / 256.0 * 100
        
        # Format based on highest unit
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}.{int(subsec_decimal):02d}"
        else:
            return f"{minutes}:{seconds:02d}.{int(subsec_decimal):02d}"

    def _draw_piece_events_from_payload(self, payload: bytes):
        """
        Print a compact list of piece events extracted from the payload.

        Each event in the payload is encoded as two bytes:
          - 0x40: lift,  followed by the square byte (controller indexing)
          - 0x41: place, followed by the square byte (controller indexing)

        The square byte is converted to a chess coordinate (e.g., "e4").
        Output is prefixed with the current packet counter, for example:
            [P012] ↑ e2 ↓ e4
        """
        try:
            events = []
            i = 0
            while i < len(payload) - 1:
                marker = payload[i]
                if marker in (0x40, 0x41):
                    field_hex = payload[i + 1]
                    try:
                        square = self.rotateFieldHex(field_hex)
                        if 0 <= square <= 63:
                            field_name = self.convertField(square)
                            arrow = "↑" if marker == 0x40 else "↓"
                            events.append(f"{arrow} {field_name}")
                    except Exception:
                        pass
                    i += 2
                else:
                    i += 1
            if events:
                prefix = f"[P{self.packet_count:03d}] "
                print(prefix + " ".join(events))
        except Exception as e:
            print(f"Error in _draw_piece_events_from_payload: {e}")

    def wait_for_key_up(self, timeout=None, accept=None):
        """
        Block until a key-up event (button released) is received by the async listener.

        Args:
            timeout: seconds to wait, or None to wait forever
            accept: optional filter of keys; list/set/tuple of codes or names,
                    or a single code/name. Examples: accept={0x10} or {'TICK'}

        Returns:
            key object on success, or None on timeout.
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

            # accept can be a single value or an iterable; support both names and numeric codes
            if isinstance(accept, (set, list, tuple)):
                if key in accept:
                    return key
            else:
                if key == accept:
                    return key
            # otherwise continue waiting

    def get_and_reset_last_key(self):
        """
        Non-blocking: return the last key-up event as Key and reset it.
        Returns None if no key-up has been recorded since last call.
        """
        last_key_pressed = self._last_key
        self._last_key = None
        return last_key_pressed

    

    def _find_key_event_in_payload(self, payload: bytes):
        """
        Detect a key event within a key payload.

        Recognizes the common preamble sequence:
            00 14 0a 05 <code> 00   (key down)
            00 14 0a 05 00 <code>   (key up)

        Returns (code_index, code_value, is_down) or (None, None, None) if not found.
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

    

    def _draw_key_event_from_payload(self, payload: bytes, code_index: int, code_val: int, is_down: bool):
        """
        Print a single-line key event indicator using only payload data.

        The output is prefixed with the current packet counter and shows the
        human-readable key name and direction arrow, for example:
            [P034] TICK ↑
        """
        base_name = DGT_BUTTON_CODES.get(code_val, f"0x{code_val:02x}")
        prefix = f"[P{self.packet_count:03d}] "
        print(prefix + f"{base_name} {'↓' if is_down else '↑'}")
        return True

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
        tosend = bytearray([command])
        if data is not None:
            len_packet = len(data) + 6
            len_hi = (len_packet >> 7) & 0x7F   # upper 7 bits
            len_lo = len_packet & 0x7F          # lower 7 bits
            tosend.append(len_hi)
            tosend.append(len_lo)
        tosend.append(self.addr1 & 0xFF)
        tosend.append(self.addr2 & 0xFF)
        if data is not None:
            tosend.extend(data)
        tosend.append(self.checksum(tosend))
        return tosend
    
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
        if command_name != command.DGT_BUS_POLL_KEYS and command_name != command.DGT_BUS_SEND_CHANGES:
            print(f"sendPacket: {command_name} ({spec.cmd}) {' '.join(f'{b:02x}' for b in tosend[:16])}")
        self.ser.write(tosend)
    
    def request_response(self, command_name: str, data: Optional[bytes]=None, timeout=2.0, callback=None, raw_len: Optional[int]=None, retries=0):
        """
        Send a command and either block until the matching response arrives (callback=None)
        returning the payload bytes, or return immediately (callback provided) and
        invoke callback(payload, None) on response or callback(None, TimeoutError) on timeout.

        Args:
            command_name (str): command name to send (e.g., "DGT_BUS_SEND_CHANGES")
            data (bytes): optional payload to include with command
            timeout (float): seconds to wait for response per attempt
            callback (callable|None): function (payload: bytes|None, err: Exception|None) -> None
            raw_len (int|None): if set, use raw byte capture mode
            retries (int): number of retry attempts on timeout (default 0)

        Returns:
            bytes for blocking mode; None for non-blocking mode

        Raises:
            TimeoutError: if no matching response within timeout (blocking mode)
            ValueError: if command is not recognized for matching
            RuntimeError: if another request is already waiting for a response
        """
        if not isinstance(command_name, str):
            raise TypeError("request_response requires a command name (str)")
        if raw_len is not None:
            return self._request_response_raw(command_name, data, timeout, callback, raw_len)
        elif callback is None:
            return self._request_response_blocking(command_name, data, timeout, retries)
        else:
            return self._request_response_async(command_name, data, timeout, callback)
    def _request_response_raw(self, command_name: str, data, timeout, callback, raw_len):
        """Handle raw byte capture mode"""
        # ensure no packet-mode waiter is active
        with self._waiter_lock:
            if self._response_waiter is not None:
                raise RuntimeError("Another request is already waiting for a response")

        q = None
        with self._raw_waiter_lock:
            if self._raw_waiter is not None:
                raise RuntimeError("Another request is already waiting for a response")
            waiter = {'target_len': int(raw_len), 'buf': bytearray(), 'callback': callback}
            if callback is None:
                q = queue.Queue(maxsize=1)
                waiter['queue'] = q
            self._raw_waiter = waiter

        # Drain serial input BEFORE sending the command to avoid stale bytes in raw buffer
        try:
            # Preferred in pyserial ≥ 3.x
            self.ser.reset_input_buffer()
        except Exception:
            try:
                n = getattr(self.ser, 'in_waiting', 0) or 0
                if n:
                    self.ser.read(n)
            except Exception:
                # final bounded drain
                try:
                    self.ser.read(10000)
                except Exception:
                    pass

        # Also clear parser buffer so header detection won't prepend stale bytes
        print(f"Clearing response buffer in request_response_raw")
        self.response_buffer = bytearray()

        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)
        self.sendPacket(command_name, eff_data)

        if callback is not None:
            return None

        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            # Snapshot/log what we collected so far in raw mode
            buf = None
            with self._raw_waiter_lock:
                if self._raw_waiter is not None and self._raw_waiter.get('queue') is q:
                    try:
                        buf = bytes(self._raw_waiter.get('buf', b''))
                    except Exception:
                        buf = None
                    self._raw_waiter = None
            try:
                if buf is not None:
                    hex_row = ' '.join(f'{b:02x}' for b in buf)
                    print(f"raw timeout: wanted={raw_len} got={len(buf)} bytes: {hex_row}")
                else:
                    print(f"raw timeout: wanted={raw_len} got=unknown (waiter cleared)")
                rb = bytes(self.response_buffer)
                print(f"parser buffer at timeout len={len(rb)}: {' '.join(f'{b:02x}' for b in rb)}")
            except Exception:
                pass
            raise TimeoutError("Timed out waiting for raw response bytes")

    def _request_response_blocking(self, command_name: str, data, timeout, retries):
        """Handle blocking mode with retry support"""
        expected_type = self._expected_type_for_cmd(command_name)
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)

        # Try to acquire request lock with timeout (prevent concurrent requests)
        lock_timeout = timeout * (retries + 1)  # Total time for all attempts
        if not self._request_lock.acquire(blocking=True, timeout=lock_timeout):
            print(f"Request queue busy, timed out after {lock_timeout}s")
            return None

        try:
            attempt = 0
            max_attempts = retries + 1
            
            while attempt < max_attempts:
                attempt += 1
                q = queue.Queue(maxsize=1)
                
                # Use try/finally to ensure waiter is always cleared
                waiter_set = False
                try:
                    with self._waiter_lock:
                        if self._response_waiter is not None:
                            # Should not happen with request lock, but check anyway
                            print("Warning: waiter still set despite request lock")
                            self._response_waiter = None
                        self._response_waiter = {'expected_type': expected_type, 'queue': q, 'callback': None, 'timer': None}
                        waiter_set = True

                    self.sendPacket(command_name, eff_data)

                    try:
                        payload = q.get(timeout=timeout)
                        return payload
                    except queue.Empty:
                        # Timeout, will retry or return None
                        pass
                        
                finally:
                    # Always cleanup waiter, even if exception
                    if waiter_set:
                        with self._waiter_lock:
                            if self._response_waiter is not None and self._response_waiter.get('queue') is q:
                                self._response_waiter = None
                
                # If last attempt, log and return None
                if attempt >= max_attempts:
                    try:
                        rb = bytes(self.response_buffer)
                        print(
                            f"packet timeout after {max_attempts} attempt(s): expected_type=0x{expected_type:02x} "
                            f"parser buffer len={len(rb)}: {' '.join(f'{b:02x}' for b in rb)}"
                        )
                    except Exception:
                        pass
                    return None
                
                # Retry after small delay
                print(f"Retry {attempt}/{max_attempts} after timeout...")
                time.sleep(0.1)
            
            return None
        finally:
            # Always release request lock
            self._request_lock.release()

    def _request_response_async(self, command_name: str, data, timeout, callback):
        """Handle non-blocking callback mode"""
        expected_type = self._expected_type_for_cmd(command_name)
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise KeyError(f"Unknown command name: {command_name}")
        eff_data = data if data is not None else (spec.default_data if spec.default_data is not None else None)

        def _on_timeout():
            with self._waiter_lock:
                w = self._response_waiter
                if w is not None and w.get('callback') is callback:
                    self._response_waiter = None
            # dispatch timeout callback on separate thread
            def _dispatch_timeout():
                try:
                    callback(None, TimeoutError("Timed out waiting for matching response packet"))
                except Exception:
                    pass
            threading.Thread(target=_dispatch_timeout, daemon=True).start()

        t = threading.Timer(timeout, _on_timeout)
        with self._waiter_lock:
            if self._response_waiter is not None:
                raise RuntimeError("Another request is already waiting for a response")
            self._response_waiter = {'expected_type': expected_type, 'queue': None, 'callback': callback, 'timer': t}

        t.start()
        # Send after registering waiter to avoid race
        self.sendPacket(command_name, eff_data)
        return None

    def _expected_type_for_cmd(self, command_name: str):
        """Map a command name to the expected inbound packet type byte."""
        if not command_name:
            raise ValueError("Empty command name")
        spec = CMD_BY_NAME.get(command_name)
        if not spec:
            raise ValueError(f"Unsupported command name: {command_name}")
        return spec.expected_resp_type

    def _extract_payload(self, packet):
        """
        Extract full payload bytes from a complete packet, excluding headers and checksum.
        Returns bytes after addr2 up to (excluding) checksum for all packet types.
        """
        if not packet or len(packet) < 6:
            return b''
        return bytes(packet[5:len(packet)-1])
    
    # def readSerial(self, num_bytes=1000):
    #     """
    #     Read data from serial port.
        
    #     Args:
    #         num_bytes (int): number of bytes to attempt to read
            
    #     Returns:
    #         bytes: data read from serial port
    #     """
    #     try:
    #         return self.ser.read(num_bytes)
    #     except:
    #         return self.ser.read(num_bytes)
    
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
            print("Discovery: STARTING - sending 0x4d and 0x4e")
            self.sendPacket(command.DGT_RETURN_BUSADRES)
            return

        print(f"Discovery: packet: {' '.join(f'{b:02x}' for b in packet)}")
        # Called from processResponse() with a complete packet
        if packet[0] == 0x90:
            self.addr1 = packet[3]
            self.addr2 = packet[4]
            self.ready = True
            print(f"Discovery: READY - addr1={hex(self.addr1)}, addr2={hex(self.addr2)}")
            self.sendPacket(command.DGT_BUS_POLL_KEYS) #Key detection enabled
    
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
        print("AsyncCentaur cleaned up")

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
        # Clear outstanding waiter (packet mode)
        try:
            with self._waiter_lock:
                w = self._response_waiter
                if isinstance(w, dict):
                    try:
                        timer = w.get('timer')
                        if timer:
                            try:
                                timer.cancel()
                            except Exception:
                                pass
                    except Exception:
                        pass
                self._response_waiter = None
        except Exception:
            pass

        # Clear raw waiter
        try:
            with self._raw_waiter_lock:
                self._raw_waiter = None
        except Exception:
            pass

    def _cleanup_serial(self):
        """Clear buffers and close serial port"""
        # Reset parser buffer and drain serial
        try:
            print(f"Clearing response buffer in _cleanup_serial")
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

        # Mark not-ready and close serial
        self.ready = False
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass

        self._last_key = None


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

    def poll_piece_detection(self):
        print(f"poll_piece_detection")
        self.sendPacket(command.DGT_BUS_SEND_CHANGES)

    def clearBoardData(self):
        print(f"clearBoardData")
        self.sendPacket(command.DGT_BUS_SEND_CHANGES)

    def beep(self, sound_name: str):
        print(f"beep: {sound_name}")
        # Ask the centaur to make a beep sound by name
        self.sendPacket(sound_name)

    def ledsOff(self):
        print(f"ledsOff")
        # Switch the LEDs off on the centaur
        self.sendPacket(command.LED_OFF_CMD)

    def ledArray(self, inarray, speed = 3, intensity=5):
        print(f"ledArray: {inarray} {speed} {intensity}")
        # Lights all the leds in the given inarray with the given speed and intensity
        data = bytearray([0x05])
        data.append(speed)
        data.append(0)
        data.append(intensity)
        for i in range(0, len(inarray)):
            data.append(self.rotateField(inarray[i]))

        self.sendPacket(command.LED_FLASH_CMD, data)

    def ledFromTo(self, lfrom, lto, intensity=5):
        print(f"ledFromTo: {lfrom} {lto} {intensity}")
        # Light up a from and to LED for move indication
        # Note the call to this function is 0 for a1 and runs to 63 for h8
        # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
        # Recalculate lfrom to the different indexing system
        data = bytearray([0x05, 0x03, 0x00])
        data.append(intensity)
        data.append(self.rotateField(lfrom))
        data.append(self.rotateField(lto))
        self.sendPacket(command.LED_FLASH_CMD, data)

    def led(self, num, intensity=5):
        # Flashes a specific led
        # Note the call to this function is 0 for a1 and runs to 63 for h8
        # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
        print(f"led: {num} {intensity}")
        # Recalculate num to the different indexing system
        data = bytearray([0x05, 0x0a, 0x01])
        data.append(intensity)
        data.append(self.rotateField(num))
        self.sendPacket(command.LED_FLASH_CMD, data)

    def ledFlash(self):
        print(f"ledFlash")
        # Flashes the last led lit by led(num) above
        self.sendPacket(command.LED_FLASH_CMD)
        #ser.read(100000)

    def sleep(self):
        print(f"sleep")
        """
        Sleep the controller.
        """
        print(f"Sleeping the centaur")
        self.sendPacket(command.DGT_SLEEP)
