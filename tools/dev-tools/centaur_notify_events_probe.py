#!/usr/bin/env python3
"""
DGT_NOTIFY_EVENTS probe

Behavior:
- Discover board address using 0x46:
  - Send 0x46 with addr=00 00, wait for 0x90; set addr from packet[3], packet[4]
  - Send 0x46 again with the discovered addr, wait for matching 0x90
- Send DGT_NOTIFY_EVENTS (0x58) to enable notifications
- When a notification event arrives (0x8e piece event or 0xa3 key event):
  - Log the event payload
  - Send DGT_BUS_SEND_CHANGES (0x83)
  - Wait for response (0x85) and log its payload
  - Reissue DGT_NOTIFY_EVENTS (0x58)

Notes:
- Outbound framing (short bus command): [cmd][addr1][addr2][data...][checksum]
- Inbound framing (typical): [type][len_hi][len_lo][addr1][addr2][payload...][checksum]
  where length is 14-bit: ((len_hi & 0x7F) << 7) | (len_lo & 0x7F)
"""

import argparse
import sys
import time
import threading
from typing import Optional, Tuple, List
from datetime import datetime

try:
    import serial  # pyserial
except Exception as e:
    print("pyserial is required. pip install pyserial")
    raise


def hexrow(b: bytes) -> str:
    return ' '.join(f"{x:02x}" for x in b)


def checksum(barr: bytes) -> int:
    total = 0
    for c in barr:
        total += c
    return total % 128


SUBSEC_DIVISOR = 256.0  # 1 tick = 1/256 s


def decode_time(packet: bytes) -> float:
    """
    Decode a time packet.
    Rules:
      - If packet[1:3] == b'\x7c\x03', treat packet[3:] as time bytes.
      - Otherwise, the whole packet is time bytes (no header present).
      - Time bytes are hierarchical: b0=subsec (1/256 s), b1=sec, b2=min, b3=hour.
      - No implicit +1 second anywhere.
    """
    if len(packet) == 0:
        return 0.0

    # Detect header at positions 1..2
    has_header = len(packet) >= 3 and packet[1:3] == b"\x7c\x03"
    time_bytes = packet[3:] if has_header else packet

    # Pull fields if present
    b0 = time_bytes[0] if len(time_bytes) > 0 else 0
    b1 = time_bytes[1] if len(time_bytes) > 1 else 0
    b2 = time_bytes[2] if len(time_bytes) > 2 else 0
    b3 = time_bytes[3] if len(time_bytes) > 3 else 0

    return (b0 / SUBSEC_DIVISOR) + b1 + (60 * b2) + (3600 * b3)


def _ts() -> str:
    now = datetime.now()
    return f"{now.strftime('%Y-%m-%d %H:%M:%S')}.{now.microsecond // 1000:03d}"


def out(msg: str):
    try:
        print(f"{_ts()} {msg}", flush=True)
    except Exception:
        pass


class PacketReader:
    """
    Serial packet reader that parses framed packets and exposes:
    - log of all packets (timestamp, bytes)
    - wait_for_type(type_byte, timeout)
    - notice handler invoked on 0x8e or 0xa3
    """

    def __init__(self, ser: serial.Serial):
        self.ser = ser
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._cv = threading.Condition()
        self.log: List[Tuple[float, bytes]] = []
        self._inbox: List[Tuple[float, bytes]] = []
        self._notice_handler = None
        self.packet_count = 0

    def set_notice_handler(self, handler):
        self._notice_handler = handler

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.0)

    def _run(self):
        while not self._stop.is_set():
            try:
                b = self.ser.read(1)
                if not b:
                    continue
                byte_val = b[0]
                # Calculate position based on current buffer state (before appending)
                with self._lock:
                    pos = self._calculate_position()
                annotation = self._format_byte_annotation(byte_val, pos)
                try:
                    out(f"raw byte: {byte_val:02x} {annotation}")
                except Exception:
                    pass
                self._append(b[0])
            except Exception:
                time.sleep(0.01)

    def _calculate_position(self) -> int:
        """
        Calculate the position of the next byte to be appended,
        relative to the most recent packet start in the buffer.
        """
        if len(self._buf) < 3:
            return len(self._buf)
        
        # Search backwards from the end to find the most recent packet start
        packet_start = -1
        for start_idx in range(len(self._buf) - 2, -1, -1):
            if start_idx + 2 >= len(self._buf):
                continue
            len_hi = self._buf[start_idx + 1]
            len_lo = self._buf[start_idx + 2]
            pkt_len = ((len_hi & 0x7F) << 7) | (len_lo & 0x7F)
            if 5 <= pkt_len <= 200:  # Reasonable packet length
                # Check if this packet could still be incomplete (hasn't been consumed)
                expected_end = start_idx + pkt_len
                if expected_end >= len(self._buf):  # Packet still incomplete or just completed
                    packet_start = start_idx
                    break
        
        if packet_start >= 0:
            # Position relative to the packet start (len(_buf) is current length before append)
            return len(self._buf) - packet_start
        else:
            # No valid packet start found, use buffer length
            return len(self._buf)

    def _format_byte_annotation(self, byte_val: int, position: int) -> str:
        """
        Format byte annotation based on position and value.
        Position 0: TYPE
        Position 1-2: LEN
        Position 3: ADDR1
        Position 4: ADDR2
        Position 5+: payload bytes (0x40=LIFT, 0x41=PLACE, else int value)
        """
        if position == 0:
            return "TYPE"
        elif position == 1 or position == 2:
            return "LEN"
        elif position == 3:
            return "ADDR1"
        elif position == 4:
            return "ADDR2"
        else:
            # Payload byte
            if byte_val == 0x40:
                return "LIFT"
            elif byte_val == 0x41:
                return "PLACE"
            else:
                return str(byte_val)

    def _append(self, v: int):
        with self._lock:
            self._buf.append(v)
            self._scan_for_packets()

    def _scan_for_packets(self):
        i = 0
        while i + 3 <= len(self._buf):
            t = self._buf[i]
            len_hi = self._buf[i + 1]
            len_lo = self._buf[i + 2]
            pkt_len = ((len_hi & 0x7F) << 7) | (len_lo & 0x7F)
            if pkt_len < 5:
                i += 1
                continue
            end = i + pkt_len
            if end > len(self._buf):
                break
            pkt = bytes(self._buf[i:end])
            # Accept packet even if checksum mismatches for notice-like frames
            bad_csum = (checksum(pkt[:-1]) != pkt[-1])
            ts = time.monotonic()
            with self._cv:
                self.log.append((ts, pkt))
                self._inbox.append((ts, pkt))
                self._cv.notify_all()
            try:
                label = "BAD_CSUM" if bad_csum else "OK"
                # For valid packets, decode time from payload and append to header line
                time_str = ""
                if not bad_csum and len(pkt) >= 6:
                    payload = pkt[5:-1]  # Payload is after addr1, addr2, before checksum
                    if payload:
                        decoded_time = decode_time(payload)
                        time_str = f"  [decoded_time={decoded_time:.3f}s]"
                out(f"raw packet ({label}): {hexrow(pkt)}{time_str}")
                
                # Handle 0x85 (board changes) payload logging
                if pkt and pkt[0] == 0x85:
                    self.packet_count += 1
                    payload = pkt[5:-1] if len(pkt) >= 6 else b""
                    if payload:
                        self.handle_board_payload(payload)
                
                if pkt and pkt[0] in (0x8E, 0xA3) and self._notice_handler is not None:
                    def _dispatch(p=pkt):
                        try:
                            self._notice_handler(p)
                        except Exception:
                            pass
                    threading.Thread(target=_dispatch, daemon=True).start()
            except Exception:
                pass
            del self._buf[:end]
            i = 0

    def handle_board_payload(self, payload: bytes):
        """
        Handle board payload logging (from async_centaur.handle_board_payload).
        Only includes logging, no callbacks.
        """
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
                out(f"[P{self.packet_count:03d}] {hex_row}{time_str}")
                self._draw_piece_events_from_payload(payload)

                # Log individual piece events
                try:
                    i = 0
                    while i < len(payload) - 1:
                        piece_event = payload[i]
                        if piece_event in (0x40, 0x41):
                            # 0 is lift, 1 is place
                            piece_event_type = 0 if piece_event == 0x40 else 1
                            field_hex = payload[i + 1]
                            try:
                                event_name = 'LIFT' if piece_event_type == 0 else 'PLACE'
                                time_in_seconds = self._get_seconds_from_time_bytes(time_bytes)
                                out(f"[P{self.packet_count:03d}] piece_event={event_name} field_hex={field_hex} time_in_seconds={time_in_seconds}")
                            except Exception as e:
                                out(f"Error processing piece event: {e}")
                            i += 2
                        else:
                            i += 1
                except Exception as e:
                    out(f"Error processing piece events: {e}")

        except Exception as e:
            out(f"Error in handle_board_payload: {e}")

    def _extract_time_from_payload(self, payload: bytes) -> bytes:
        """
        Return the time bytes prefix from a board payload.
        The board payload layout is:
            [optional time bytes ...] [events ...]
        where events are pairs of bytes starting with 0x40 (lift) or 0x41 (place),
        followed by the field hex. This function returns all bytes before the
        first event marker (0x40/0x41).
        """
        out_bytes = bytearray()
        for b in payload:
            if b in (0x40, 0x41):
                break
            out_bytes.append(b)
        return bytes(out_bytes)

    def _get_seconds_from_time_bytes(self, time_bytes):
        """
        Return the seconds from the time bytes.
        """
        if len(time_bytes) == 0:
            return 0
        time_in_seconds = time_bytes[0] / 256.0
        time_in_seconds += time_bytes[1] if len(time_bytes) > 1 else 0
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
        """
        if len(time_bytes) == 0:
            return ""
        
        subsec = time_bytes[0] if len(time_bytes) > 0 else 0
        seconds = time_bytes[1] if len(time_bytes) > 1 else 0
        minutes = time_bytes[2] if len(time_bytes) > 2 else 0
        hours = time_bytes[3] if len(time_bytes) > 3 else 0
        
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
                    arrow = "↑" if marker == 0x40 else "↓"
                    events.append(f"{arrow} {field_hex:02x}")
                    i += 2
                else:
                    i += 1
            if events:
                prefix = f"[P{self.packet_count:03d}] "
                out(prefix + " ".join(events))
        except Exception as e:
            out(f"Error in _draw_piece_events_from_payload: {e}")

    def wait_for_type(self, type_byte: int, timeout: float) -> Optional[bytes]:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            with self._cv:
                for idx, (ts, pkt) in enumerate(self._inbox):
                    if pkt and pkt[0] == type_byte:
                        self._inbox.pop(idx)
                        return pkt
                self._cv.wait(timeout=min(0.1, max(0.0, remaining)))


def drain_serial(ser: serial.Serial):
    try:
        ser.reset_input_buffer()
    except Exception:
        try:
            n = getattr(ser, 'in_waiting', 0) or 0
            if n:
                ser.read(n)
        except Exception:
            try:
                ser.read(8192)
            except Exception:
                pass


def build_short(cmd: int, addr1: int, addr2: int, data: bytes = b"") -> bytes:
    tosend = bytearray(bytes([cmd]) + addr1.to_bytes(1, 'big') + addr2.to_bytes(1, 'big') + (data or b""))
    tosend.append(checksum(tosend))
    return bytes(tosend)


def discover_with_0x46(ser: serial.Serial, reader: PacketReader, timeout: float = 5.0) -> Tuple[int, int]:
    """
    Discovery flow matching async_centaur.py logic using 0x46.
    1) Send 0x46 with addr=00 00 → expect 0x90; set (addr1, addr2) from packet.
    2) Send 0x46 again with (addr1, addr2) → expect 0x90 that matches.
    Returns (addr1, addr2) or raises RuntimeError on failure.
    """
    drain_serial(ser)

    # Step 1: query with zeros
    pkt = build_short(0x46, 0x00, 0x00)
    out(f"send discovery (step1): {hexrow(pkt)}")
    try:
        ser.write(pkt)
    except Exception as e:
        raise RuntimeError(f"failed to write discovery step1: {e}")
    pkt90 = reader.wait_for_type(0x90, timeout)
    if pkt90 is None or len(pkt90) < 5:
        raise RuntimeError("discovery step1 timeout or short 0x90")
    addr1, addr2 = pkt90[3], pkt90[4]
    out(f"step1: addr1={addr1:02x} addr2={addr2:02x}")

    # Step 2: confirm
    pkt2 = build_short(0x46, addr1, addr2)
    out(f"send discovery (step2): {hexrow(pkt2)}")
    try:
        ser.write(pkt2)
    except Exception as e:
        raise RuntimeError(f"failed to write discovery step2: {e}")
    pkt90b = reader.wait_for_type(0x90, timeout)
    if pkt90b is None or len(pkt90b) < 5:
        raise RuntimeError("discovery step2 timeout or short 0x90")
    if pkt90b[3] != addr1 or pkt90b[4] != addr2:
        raise RuntimeError("discovery step2 addr mismatch")
    out("discovery complete (READY)")
    return addr1, addr2


def send_notify_events(ser: serial.Serial, addr1: int, addr2: int):
    """
    Send DGT_NOTIFY_EVENTS (0x58) to enable notifications.
    """
    pkt = build_short(0x58, addr1, addr2)
    out(f"send DGT_NOTIFY_EVENTS (0x58): {hexrow(pkt)}")
    ser.write(pkt)


def send_bus_send_changes(ser: serial.Serial, addr1: int, addr2: int):
    """
    Send DGT_BUS_SEND_CHANGES (0x83).
    """
    pkt = build_short(0x83, addr1, addr2)
    out(f"send DGT_BUS_SEND_CHANGES (0x83): {hexrow(pkt)}")
    ser.write(pkt)


def main():
    ap = argparse.ArgumentParser(description="DGT_NOTIFY_EVENTS probe: discover → 0x58 → log events → 0x83 → 0x85 → reissue 0x58")
    ap.add_argument("--port", default="/dev/serial0", help="Serial device (e.g., /dev/serial0)")
    ap.add_argument("--baud", type=int, default=1000000, help="Baud rate")
    ap.add_argument("--listen", type=float, default=300.0, help="Seconds to listen for notifications")
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, baudrate=args.baud, timeout=0.2)
    except Exception as e:
        out(f"failed to open serial {args.port}@{args.baud}: {e}")
        sys.exit(1)

    reader = PacketReader(ser)
    reader.start()

    try:
        out("attempting discovery via 0x46...")
        addr1, addr2 = discover_with_0x46(ser, reader, timeout=5.0)
        out(f"discovered addr1={addr1:02x} addr2={addr2:02x}")

        # Notice handler: on 0x8e or 0xa3, log payload, send 0x83, wait for 0x85, then reissue DGT_NOTIFY_EVENTS
        def on_notice(pkt: bytes):
            try:
                event_type = pkt[0] if pkt else 0
                event_name = "PIECE_EVENT" if event_type == 0x8E else "KEY_EVENT" if event_type == 0xA3 else "UNKNOWN"
                payload = pkt[5:-1] if len(pkt) >= 6 else b""
                out(f"event received: type=0x{event_type:02x} ({event_name}) payload={hexrow(payload)}")
                
                # Send DGT_BUS_SEND_CHANGES and wait for response
                time.sleep(0.01)  # Small delay before sending
                send_bus_send_changes(ser, addr1, addr2)
                
                # Wait for 0x85 response
                resp = reader.wait_for_type(0x85, timeout=2.0)
                if resp is not None:
                    resp_payload = resp[5:-1] if len(resp) >= 6 else b""
                    out(f"changes response (0x85) payload: {hexrow(resp_payload)}")
                else:
                    out("warning: timeout waiting for 0x85 response")
                
                # Reissue DGT_NOTIFY_EVENTS after receiving changes response
                time.sleep(0.01)  # Small delay before reissuing
                send_notify_events(ser, addr1, addr2)
            except Exception as e:
                out(f"on-notice error: {e}")

        reader.set_notice_handler(on_notice)

        # Send initial DGT_NOTIFY_EVENTS
        send_notify_events(ser, addr1, addr2)

        # Listen for events
        out(f"listening for events for {args.listen:.1f} seconds...")
        out("Move pieces or press keys to trigger events")
        t0 = time.monotonic()
        while time.monotonic() - t0 < max(0.0, args.listen):
            time.sleep(0.1)

        out("done listening.")
    finally:
        try:
            reader.stop()
        except Exception:
            pass
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

