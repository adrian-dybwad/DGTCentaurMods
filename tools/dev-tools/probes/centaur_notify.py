#!/usr/bin/env python3
"""
Centaur notification probe (0x46 discovery → 0x57 enable → 0x83 on notify)

Behavior:
- Discover `addr1`/`addr2` by sending 0x46 (as in `async_centaur.py`):
  - Send 0x46 with addr=00 00, wait for 0x90; set addr from packet[3], packet[4]
  - Send 0x46 again with the discovered addr, wait for matching 0x90
- Enable notifications by sending 0x57 (no response expected)
- When a notification packet arrives (0x8e piece event or 0xa3 key event),
  immediately send 0x83 to fetch changes (expect 0x85 response) and print payload.

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
                try:
                    out(f"raw byte: {b[0]:02x}")
                except Exception:
                    pass
                self._append(b[0])
            except Exception:
                time.sleep(0.01)

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
                out(f"raw packet ({label}): {hexrow(pkt)}")
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


def enable_notifications(ser: serial.Serial, addr1: int, addr2: int):
    """
    Send 0x57 to enable notifications (no response expected).
    """
    pkt = build_short(0x57, addr1, addr2)
    out(f"send notify-enable (0x57): {hexrow(pkt)}")
    ser.write(pkt)


def poll_changes(ser: serial.Serial, addr1: int, addr2: int):
    """
    Send 0x83 (BUS_SEND_CHANGES). Response type should be 0x85.
    """
    pkt = build_short(0x83, addr1, addr2)
    out(f"send changes (0x83): {hexrow(pkt)}")
    ser.write(pkt)


def main():
    ap = argparse.ArgumentParser(description="Centaur notify probe: 0x46 discovery → 0x57 enable → 0x83 on notify")
    ap.add_argument("--port", default="/dev/serial0", help="Serial device (e.g., /dev/serial0)")
    ap.add_argument("--baud", type=int, default=1000000, help="Baud rate")
    ap.add_argument("--listen", type=float, default=30.0, help="Seconds to listen for notifications")
    ap.add_argument("--rearm", action="store_true", help="After polling with 0x83, send 0x57 again to keep notifications on")
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

        # Notice handler: on 0x8e or 0xa3, poll once with 0x83
        def on_notice(pkt: bytes):
            try:
                t = pkt[0] if pkt else 0
                out(f"notice pkt=0x{t:02x} -> polling 0x83")
                poll_changes(ser, addr1, addr2)
                # Rearm notifications if requested
                if args.rearm:
                    time.sleep(0.02)
                    enable_notifications(ser, addr1, addr2)
            except Exception as e:
                out(f"on-notice error: {e}")

        reader.set_notice_handler(on_notice)

        # Enable notifications once
        enable_notifications(ser, addr1, addr2)

        # Listen for both notifications and 0x85 responses, printing 0x85 payloads
        t0 = time.monotonic()
        while time.monotonic() - t0 < max(0.0, args.listen):
            pkt = reader.wait_for_type(0x85, timeout=0.2)
            if pkt is None:
                continue
            payload = pkt[5:-1] if len(pkt) >= 6 else b""
            out(f"changes (0x85) payload: {hexrow(payload)}")

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


