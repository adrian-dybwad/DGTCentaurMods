#!/usr/bin/env python3
"""
Minimal Centaur serial monitor/sender (no discovery)

Features:
- Opens serial and continuously prints:
  - raw byte: XX (every incoming byte)
  - packet: ... (only for valid framed packets)
    - Valid = checksum-correct OR notice type (0x93, 0x8e) which are checksum-free
- Interactive stdin to send one-byte commands and set addr:
  - addr 0102   -> set addr1=0x01 addr2=0x02
  - 43          -> send short packet [43][addr1][addr2][checksum]
  - q           -> quit

Notes:
- No discovery is performed; you must set the address via 'addr' if needed.
"""

import sys
import time
import threading
import argparse
from typing import List, Tuple, Optional

try:
    import serial  # pyserial
except Exception:
    print("pyserial is required. pip install pyserial")
    raise


NOTICE_TYPES = {0x93, 0x8E}


def hexrow(b: bytes) -> str:
    return ' '.join(f'{x:02x}' for x in b)


def checksum(barr: bytes) -> int:
    s = 0
    for c in barr:
        s += c
    return s % 128


class PacketReader:
    def __init__(self, ser: serial.Serial):
        self.ser = ser
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._cv = threading.Condition()
        self.log: List[Tuple[float, bytes]] = []

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
                    v = b[0]
                    if 32 <= v < 127:
                        print(f"{v:02x} {chr(v)}")
                    else:
                        print(f"{v:02x}")
                except Exception:
                    pass
                self._append(b[0])
            except Exception:
                time.sleep(0.01)

    def _append(self, v: int):
        with self._lock:
            self._buf.append(v)
            self._scan()

    def _scan(self):
        i = 0
        while i + 3 <= len(self._buf):
            t = self._buf[i]
            len_hi = self._buf[i + 1]
            len_lo = self._buf[i + 2]
            # Length is 14-bit: (hi << 7) | lo
            ln = ((len_hi & 0x7F) << 7) | (len_lo & 0x7F)
            if ln <= 0:
                i += 1
                continue
            end = i + ln
            if end > len(self._buf):
                break
            pkt = bytes(self._buf[i:end])
            is_notice = (pkt[0] in NOTICE_TYPES)
            valid = is_notice or (checksum(pkt[:-1]) == pkt[-1])
            if valid:
                ts = time.monotonic()
                self.log.append((ts, pkt))
                try:
                    # Labeled raw byte dump: add ASCII only for payload bytes
                    type_b = pkt[0]
                    len_hi_b = pkt[1] if len(pkt) > 1 else 0
                    len_lo_b = pkt[2] if len(pkt) > 2 else 0
                    addr1_b = pkt[3] if len(pkt) > 3 else 0
                    addr2_b = pkt[4] if len(pkt) > 4 else 0
                    if is_notice:
                        payload_bytes = list(pkt[5:]) if len(pkt) > 5 else []
                        cs_present = False
                        cs_b = None
                    else:
                        payload_bytes = list(pkt[5:-1]) if len(pkt) > 6 else []
                        cs_present = True
                        cs_b = pkt[-1]

                    print(f"{type_b:02x} (type)")
                    print(f"{len_hi_b:02x} (len_hi)")
                    print(f"{len_lo_b:02x} (len_lo)")
                    print(f"{addr1_b:02x} (addr1)")
                    print(f"{addr2_b:02x} (addr2)")
                    for x in payload_bytes:
                        if 32 <= x < 127:
                            print(f"{x:02x} {chr(x)}")
                        else:
                            print(f"{x:02x} (payload)")
                    if cs_present and cs_b is not None:
                        print(f"{cs_b:02x} (cs)")
                except Exception:
                    pass
            # drop this frame regardless (valid or not), advance
            del self._buf[:end]
            i = 0


def build_short(cmd: int, addr1: int, addr2: int) -> bytes:
    tosend = bytearray(bytes([cmd]) + addr1.to_bytes(1, 'big') + addr2.to_bytes(1, 'big'))
    tosend.append(checksum(tosend))
    return bytes(tosend)


def parse_hex_byte(s: str) -> Optional[int]:
    s = s.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 2 or any(c not in '0123456789abcdef' for c in s):
        return None
    return int(s, 16)


def parse_hex_two_bytes(s: str) -> Optional[Tuple[int, int]]:
    s = s.strip().lower().replace(" ", "")
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 4 or any(c not in '0123456789abcdef' for c in s):
        return None
    return int(s[:2], 16), int(s[2:], 16)


def main():
    ap = argparse.ArgumentParser(description="Minimal Centaur monitor/sender (no discovery)")
    ap.add_argument("--port", default="/dev/serial0", help="Serial device (e.g., /dev/serial0)")
    ap.add_argument("--baud", type=int, default=1000000, help="Baud rate")
    ap.add_argument("--addr", help="Initial addr1addr2 hex (e.g., 0650)")
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, baudrate=args.baud, timeout=0.2)
    except Exception as e:
        print(f"failed to open serial {args.port}@{args.baud}: {e}")
        sys.exit(1)

    addr1, addr2 = 0x00, 0x00
    if args.addr:
        parsed = parse_hex_two_bytes(args.addr)
        if parsed is None:
            print("invalid --addr; expected 4 hex digits like 0650")
        else:
            addr1, addr2 = parsed

    print(f"addr set to: {addr1:02x} {addr2:02x}")

    reader = PacketReader(ser)
    reader.start()

    print("commands:")
    print("  addr 0102  -> set addr1=0x01 addr2=0x02")
    print("  43         -> send short packet [43][addr1][addr2][checksum]")
    print("  q          -> quit")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in ("q", "quit", "exit"):
            break
        if line.lower().startswith("addr"):
            rest = line[4:].strip()
            parsed = parse_hex_two_bytes(rest)
            if parsed is None:
                print("error: usage 'addr 0102'")
                continue
            addr1, addr2 = parsed
            print(f"addr set to: {addr1:02x} {addr2:02x}")
            continue
        # Otherwise treat as one-byte command
        b = parse_hex_byte(line)
        if b is None:
            print("error: expected hex byte like 43")
            continue
        pkt = build_short(b, addr1, addr2)
        print(f"send: {hexrow(pkt)}")
        try:
            ser.write(pkt)
        except Exception as e:
            print(f"send error: {e}")

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


