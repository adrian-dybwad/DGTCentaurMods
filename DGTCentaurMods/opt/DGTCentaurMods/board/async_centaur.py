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

# Constants
LED_OFF_CMD = b'\xb0\x00\x07'
 # response header constants not needed; use exported *_RESP values

# Unified command registry
@dataclass(frozen=True)
class CommandSpec:
    cmd: bytes
    expected_resp_type: int
    default_data: Optional[bytes] = None

COMMANDS: Dict[str, CommandSpec] = {
    "DGT_BUS_SEND_SNAPSHOT":  CommandSpec(b"\xf0\x00\x07", 0xF0, b'\x7f'),
    "DGT_BUS_SEND_CHANGES":   CommandSpec(b"\x83", 0x85, None),
    "DGT_BUS_POLL_KEYS":      CommandSpec(b"\x94", 0xB1, None),
    "DGT_SEND_BATTERY_INFO":  CommandSpec(b"\x98", 0xB5, None),
    "SOUND_GENERAL":          CommandSpec(b"\xb1\x00\x08", 0xB1, b'\x4c\x08'),
    "SOUND_FACTORY":          CommandSpec(b"\xb1\x00\x08", 0xB1, b'\x4c\x40'),
    "SOUND_POWER_OFF":        CommandSpec(b"\xb1\x00\x0a", 0xB1, b'\x4c\x08\x48\x08'),
    "SOUND_POWER_ON":         CommandSpec(b"\xb1\x00\x0a", 0xB1, b'\x48\x08\x4c\x08'),
    "SOUND_WRONG":            CommandSpec(b"\xb1\x00\x0a", 0xB1, b'\x4e\x0c\x48\x10'),
    "SOUND_WRONG_MOVE":       CommandSpec(b"\xb1\x00\x08", 0xB1, b'\x48\x08'),
    "DGT_SLEEP":              CommandSpec(b"\xb2\x00\x07", 0xB1, b'\x0a'),
}


# Fast lookups
CMD_BY_CMD0 = {spec.cmd[0]: spec for spec in COMMANDS.values()}
CMD_BY_CMD  = {spec.cmd: spec for spec in COMMANDS.values()}
RESP_TYPE_TO_SPEC = {spec.expected_resp_type: spec for spec in COMMANDS.values()}

# Export importable byte constants without repeating names
globals().update({name: spec.cmd for name, spec in COMMANDS.items()})

# Export response-type constants (e.g., DGT_BUS_SEND_CHANGES_RESP)
globals().update({f"{name}_RESP": spec.expected_resp_type for name, spec in COMMANDS.items()})

# Export default data constants (e.g., DGT_BUS_SEND_CHANGES_DATA); value may be None
globals().update({f"{name}_DATA": spec.default_data for name, spec in COMMANDS.items()})

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
}

#
# Useful constants
#
# BTNBACK = 1
# BTNTICK = 2
# BTNUP = 3
# BTNDOWN = 4
# BTNHELP = 5
# BTNPLAY = 6
# BTNLONGPLAY = 7


__all__ = ['AsyncCentaur', 'DGT_BUS_SEND_CHANGES', 'DGT_BUS_POLL_KEYS', 'DGT_SEND_BATTERY_INFO', 'DGT_BUTTON_CODES']

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
        - get_and_reset_last_button()
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
        self.discovery_state = "STARTING"
        self.ready = False
        self.listener_running = True
        self.listener_thread = None
        self.spinner = itertools.cycle(['|', '/', '-', '\\'])
        self.response_buffer = bytearray()
        self.packet_count = 0
        # queue to signal key-up events as (code, name)
        self.key_up_queue = queue.Queue(maxsize=128)
        # track last key-up (code, name) for non-blocking retrieval
        self._last_button = (None, None)
        # single waiter for blocking request_response
        self._waiter_lock = threading.Lock()
        self._response_waiter = None  # dict with keys: expected_type:int, queue:Queue

        # raw byte capture waiter (bypasses checksum/length parsing)
        self._raw_waiter_lock = threading.Lock()
        self._raw_waiter = None  # {'target_len': int, 'buf': bytearray, 'queue': Queue, 'callback': Optional[Callable]}

        if auto_init:
            init_thread = threading.Thread(target=self.run_background, daemon=False)
            init_thread.start()

    
    def run_background(self, start_key_polling=False):
        """Initialize in background thread"""
        self.discovery_state = "STARTING"
        self.listener_running = True
        self.ready = False
        self._initialize()
        
        # Start listener thread FIRST so it's ready to capture responses
        self.listener_thread = threading.Thread(target=self._listener_thread, daemon=True)
        self.listener_thread.start()

        # THEN send discovery commands
        print("Sending discovery commands")
        self._discover_board_address()
        # print(f"start_key_polling: {start_key_polling}")
        # if start_key_polling:
        #     self.sendPacket(DGT_BUS_POLL_KEYS)
        # print("Key polling started")
        
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
        Process incoming byte - handle discovery state machine first, then normal parsing.
        Supports two packet formats:
        
        Format 1 (old): [data...][addr1][addr2][checksum]
        Format 2 (new): [0x85][0x00][data...][addr1][addr2][checksum]
        
        Both have [addr1][addr2][checksum] pattern at the end.
        Packet boundary is detected when:
        1. Buffer ends with valid [addr1][addr2][checksum], OR
        2. A new 85 00 header is detected (indicating start of next packet)
        """
        print(f"Processing response: {byte}")
        # Detect packet start sequence (<START_TYPE_BYTE> 00) while buffer has data
        HEADER_DATA_BYTES = 4
        if (len(self.response_buffer) >= HEADER_DATA_BYTES and 
            self.response_buffer[-HEADER_DATA_BYTES] in START_TYPE_BYTES and 
            self.response_buffer[-HEADER_DATA_BYTES+1] == self.addr1 and
            byte == self.addr2 and 
            len(self.response_buffer) > HEADER_DATA_BYTES):
            print(f"Packet start detected: {self.response_buffer[-HEADER_DATA_BYTES:]}")
            print(f"addr1: {self.addr1}, addr2: {self.addr2}")
            print(f"byte: {byte}")
            print(f"len(self.response_buffer): {len(self.response_buffer)}")
            print(f"START_TYPE_BYTES: {START_TYPE_BYTES}")
            print(f"HEADER_DATA_BYTES: {HEADER_DATA_BYTES}")
            print(f"self.response_buffer: {self.response_buffer}")
            # Log orphaned data (everything except the 85)
            hex_row = ' '.join(f'{b:02x}' for b in self.response_buffer[:-1])
            print(f"[ORPHANED] {hex_row}")
            self.response_buffer = bytearray([self.response_buffer[-HEADER_DATA_BYTES]])  # Keep the detected start byte, add the 00 below
            print(f"After trimming: self.response_buffer: {self.response_buffer}")
        
        self.response_buffer.append(byte)
        print(f"After appending: self.response_buffer: {self.response_buffer}")

        # Handle discovery state machine
        if self.discovery_state == "INITIALIZING":
            # Got a response to initial commands, now send discovery packet
            self._discover_board_address(self.response_buffer)

        print(f"response_buffer: {self.response_buffer}")
        # Check if this byte is a checksum boundary
        if len(self.response_buffer) >= 2:
            calculated_checksum = self.checksum(self.response_buffer[:-1])
            if byte == calculated_checksum:
                # Verify packet length matches declared length
                print(f"len(self.response_buffer): {len(self.response_buffer)}")
                print(f"self.response_buffer: {self.response_buffer}")
                print(f"byte: {byte}")
                print(f"calculated_checksum: {calculated_checksum}")
                if len(self.response_buffer) >= 6:
                    print(f"len(self.response_buffer) >= 6")
                    len_hi, len_lo = self.response_buffer[1], self.response_buffer[2]
                    declared_length = (len_hi << 7) | len_lo
                    actual_length = len(self.response_buffer)
                    print(f"declared_length: {declared_length}, actual_length: {actual_length}")
                    
                    if actual_length == declared_length:
                        # We have a valid packet
                        if self.discovery_state == "READY":
                            self.on_packet_complete(self.response_buffer)
                        else:
                            self._discover_board_address(self.response_buffer)
                        
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
                            return
                        else:
                            try:
                                q.put_nowait(payload)
                            except Exception:
                                pass
                            return
        except Exception:
            # Do not break normal flow on waiter issues
            pass

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

            self.sendPacket(DGT_BUS_SEND_CHANGES)
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
                        self._last_button = (code_val, name)
                        try:
                            self.key_up_queue.put_nowait((code_val, name))
                        except queue.Full:
                            pass

            self.sendPacket(DGT_BUS_POLL_KEYS)
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
            (code, name) on success, or (None, None) on timeout.
        """
        deadline = (time.time() + timeout) if timeout is not None else None
        while True:
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.time())
                if remaining == 0.0:
                    return (None, None)
            try:
                code, name = self.key_up_queue.get(timeout=remaining)
            except queue.Empty:
                return (None, None)

            if not accept:
                return (code, name)

            # accept can be a single value or an iterable; support both names and numeric codes
            if isinstance(accept, (set, list, tuple)):
                if code in accept or name in accept:
                    return (code, name)
            else:
                if code == accept or name == accept:
                    return (code, name)
            # otherwise continue waiting

    def get_and_reset_last_button(self):
        """
        Non-blocking: return the last key-up event as (code, name) and reset it.
        Returns (None, None) if no key-up has been recorded since last reset.
        """
        code, name = self._last_button
        self._last_button = (None, None)
        return (code, name)

    

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
        tosend = bytearray(command + self.addr1.to_bytes(1, byteorder='big') + 
                          self.addr2.to_bytes(1, byteorder='big') + data)
        tosend.append(self.checksum(tosend))
        return tosend
    
    def sendPacket(self, command, data: Optional[bytes] = None):
        """
        Send a packet to the board.
        
        Args:
            command: bytes for command
            data: bytes for data payload; if None, use default_data from COMMANDS if available
        """
        spec = CMD_BY_CMD.get(command) or CMD_BY_CMD0.get(command[0])
        eff_data = data if data is not None else (spec.default_data if spec and spec.default_data is not None else b'')
        tosend = self.buildPacket(command, eff_data)
        self.ser.write(tosend)
    
    def request_response(self, command, data: Optional[bytes]=None, timeout=2.0, callback=None, raw_len: Optional[int]=None):
        """
        Send a command and either block until the matching response arrives (callback=None)
        returning the payload bytes, or return immediately (callback provided) and
        invoke callback(payload, None) on response or callback(None, TimeoutError) on timeout.

        Args:
            command (bytes): command bytes to send (e.g., DGT_BUS_SEND_CHANGES)
            data (bytes): optional payload to include with command
            timeout (float): seconds to wait for response
            callback (callable|None): function (payload: bytes|None, err: Exception|None) -> None

        Returns:
            bytes for blocking mode; None for non-blocking mode

        Raises:
            TimeoutError: if no matching response within timeout (blocking mode)
            ValueError: if command is not recognized for matching
            RuntimeError: if another request is already in progress
        """
        # RAW capture path
        if raw_len is not None:
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
            self.response_buffer = bytearray()

            spec = CMD_BY_CMD.get(command) or CMD_BY_CMD0.get(command[0])
            eff_data = data if data is not None else (spec.default_data if spec and spec.default_data is not None else b'')
            self.sendPacket(command, eff_data)

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

        expected_type = self._expected_type_for_cmd(command)
        spec = CMD_BY_CMD.get(command) or CMD_BY_CMD0.get(command[0])
        eff_data = data if data is not None else (spec.default_data if spec and spec.default_data is not None else b'')

        if callback is None:
            # Blocking mode
            q = queue.Queue(maxsize=1)
            with self._waiter_lock:
                if self._response_waiter is not None:
                    raise RuntimeError("Another blocking request is already waiting for a response")
                self._response_waiter = {'expected_type': expected_type, 'queue': q, 'callback': None, 'timer': None}

            # Send after registering waiter to avoid race
            self.sendPacket(command, eff_data)

            try:
                payload = q.get(timeout=timeout)
                return payload
            except queue.Empty:
                # Cleanup waiter if still set
                with self._waiter_lock:
                    if self._response_waiter is not None and self._response_waiter.get('queue') is q:
                        self._response_waiter = None
            # Log what the parser has buffered so far
            try:
                rb = bytes(self.response_buffer)
                print(
                    f"packet timeout: expected_type=0x{expected_type:02x} "
                    f"parser buffer len={len(rb)}: {' '.join(f'{b:02x}' for b in rb)}"
                )
            except Exception:
                pass
                raise TimeoutError("Timed out waiting for matching response packet")

        # Non-blocking mode with callback
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
        self.sendPacket(command, eff_data)
        return None

    def _expected_type_for_cmd(self, command):
        """Map an outbound command to the expected inbound packet type byte."""
        if not command:
            raise ValueError("Empty command")
        spec = CMD_BY_CMD.get(command) or CMD_BY_CMD0.get(command[0])
        if not spec:
            raise ValueError(f"Unsupported command: 0x{command[0]:02x}")
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
        if self.discovery_state == "READY":
            return
        
        # Called from run_background() with no packet
        if packet is None:
            if self.discovery_state == "STARTING":
                self.discovery_state = "INITIALIZING"
                print("Discovery: STARTING - sending 0x4d and 0x4e")
                tosend = bytearray(b'\x4d\x4e')
                self.ser.write(tosend)
            return

        # Called from processResponse() with a complete packet
        if self.discovery_state == "INITIALIZING":
            self.discovery_state = "AWAITING_PACKET"
            hex_row = ' '.join(f'{b:02x}' for b in packet)
            #print(f"[INIT_RESPONSE] {hex_row}")
            print("Discovery: sending discovery packet 0x87 0x00 0x00 0x07")
            tosend = bytearray(b'\x87\x00\x00\x07')
            self.ser.write(tosend)
        
        elif self.discovery_state == "AWAITING_PACKET":
            if len(packet) > 4:
                self.addr1 = packet[3]
                self.addr2 = packet[4]
                self.discovery_state = "READY"
                self.ready = True
                print(f"Discovery: READY - addr1={hex(self.addr1)}, addr2={hex(self.addr2)}")
                self.sendPacket(DGT_BUS_POLL_KEYS) #Key detection enabled
                #self.sendPacket(DGT_BUS_SEND_CHANGES) #Piece detection enabled
                #  (No need to send this here, it will be sent in the handle_board_packet function when the board is ready  )
    
    def close(self):
        """Close the serial connection"""
        self.stop_listener()
        if self.ser:
            self.ser.close()
            print("Serial port closed")

    def clearSerial(self):
        #TODO: Reset things, clear lastKey, moves that may have accumulated etc. 
        #Rename this function to something like resetBoardState()
        self._last_button = (None, None)
        #self.sendPacket(DGT_BUS_SEND_CHANGES)
        #self.sendPacket(DGT_BUS_POLL_KEYS)

        print('Board is idle.')

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
        self.sendPacket(DGT_BUS_SEND_CHANGES)

    def clearBoardData(self):
        self.sendPacket(DGT_BUS_SEND_CHANGES)

    def beep(self, beeptype):
        # Ask the centaur to make a beep sound
        self.sendPacket(beeptype)

    def ledsOff(self):
        # Switch the LEDs off on the centaur
        self.sendPacket(LED_OFF_CMD, b'\x00')

    def ledArray(self, inarray, speed = 3, intensity=5):
        # Lights all the leds in the given inarray with the given speed and intensity
        tosend = bytearray(b'\xb0\x00\x0c' + self.addr1.to_bytes(1, byteorder='big') + self.addr2.to_bytes(1, byteorder='big') + b'\x05')
        tosend.append(speed)
        tosend.append(0)
        tosend.append(intensity)
        for i in range(0, len(inarray)):
            tosend.append(self.rotateField(inarray[i]))
        tosend[2] = len(tosend) + 1
        tosend.append(self.checksum(tosend))
        self.ser.write(tosend)

    def ledFromTo(self, lfrom, lto, intensity=5):
        # Light up a from and to LED for move indication
        # Note the call to this function is 0 for a1 and runs to 63 for h8
        # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
        tosend = bytearray(b'\xb0\x00\x0c' + self.addr1.to_bytes(1, byteorder='big') + self.addr2.to_bytes(1, byteorder='big') + b'\x05\x03\x00\x05\x3d\x31\x0d')
        # Recalculate lfrom to the different indexing system
        tosend[8] = intensity
        tosend[9] = self.rotateField(lfrom)
        # Same for lto
        tosend[10] = self.rotateField(lto)
        # Wipe checksum byte and append the new checksum.
        tosend.pop()
        tosend.append(self.checksum(tosend))
        self.ser.write(tosend)
        # Read off any data
        #ser.read(100000)

    def led(self, num, intensity=5):
        # Flashes a specific led
        # Note the call to this function is 0 for a1 and runs to 63 for h8
        # but the electronics runs 0x00 from a8 right and down to 0x3F for h1
        tcount = 0
        success = 0
        while tcount < 5 and success == 0:
            try:
                tosend = bytearray(b'\xb0\x00\x0b' + self.addr1.to_bytes(1, byteorder='big') + self.addr2.to_bytes(1, byteorder='big') + b'\x05\x0a\x01\x01\x3d\x5f')
                # Recalculate num to the different indexing system
                # Last bit is the checksum
                tosend[8] = intensity
                tosend[9] = self.rotateField(num)
                # Wipe checksum byte and append the new checksum.
                tosend.pop()
                tosend.append(self.checksum(tosend))
                self.ser.write(tosend)
                success = 1
                # Read off any data
                #ser.read(100000)
            except:
                time.sleep(0.1)
                tcount = tcount + 1

    def ledFlash(self):
        # Flashes the last led lit by led(num) above
        self.sendPacket(b'\xb0\x00\x0a', b'\x05\x0a\x00\x01')
        #ser.read(100000)

    def sleep(self):
        """
        Sleep the controller.
        """
        print(f"Sleeping the centaur")
        self.sendPacket(DGT_SLEEP)
