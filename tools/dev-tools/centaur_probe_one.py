#!/usr/bin/env python3
"""
Minimal Centaur probe (single command + optional notice-triggered poll)

Behavior:
  1) Initialize (discover addr1/addr2 via 0x4d 0x4e → 0x93, then 0x87).
  2) Send a command specified by --send HEXHEX (e.g., 4387 → send 0x43, expect 0x87).
  3) Optionally, if --on-notice HEXHEX is provided (e.g., 8e43), when an unsolicited
     packet with type 0x8e is parsed, immediately send 0x43.

Notes:
  - Prints every raw byte and every parsed packet (labels BAD_CSUM if checksum fails).
  - Short-form bus commands are framed as: [cmd][addr1][addr2][checksum].
  - Exits after the initial expected response times out or arrives; remains running
    only if --listen is provided (to catch notice-triggered polls).
"""

import argparse
import sys
import time
import threading
from typing import Optional, List, Tuple

try:
    import serial  # pyserial
except Exception as e:
    print("pyserial is required. pip install pyserial")
    raise


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
        # (ts, packet)
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
                # Raw byte
                try:
                    print(f"raw byte: {b[0]:02x}")
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
            t2 = self._buf[i+1]
            ln = self._buf[i+2]
            if t2 != 0x00 or ln < 5:
                i += 1
                continue
            end = i + ln
            if end > len(self._buf):
                break
            pkt = bytes(self._buf[i:end])
            bad = (checksum(pkt[:-1]) != pkt[-1])
            ts = time.monotonic()
            with self._cv:
                self.log.append((ts, pkt))
                self._inbox.append((ts, pkt))
                self._cv.notify_all()
            try:
                if bad:
                    print(f"raw packet (BAD_CSUM): {hexrow(pkt)}")
                else:
                    print(f"raw packet: {hexrow(pkt)}")
                if pkt and pkt[0] == 0x8E and self._notice_handler is not None:
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
            rem = deadline - time.time()
            if rem <= 0:
                return None
            with self._cv:
                for idx, (ts, pkt) in enumerate(self._inbox):
                    if pkt and pkt[0] == type_byte:
                        self._inbox.pop(idx)
                        return pkt
                self._cv.wait(timeout=min(0.1, max(0.0, rem)))


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


def discovery(ser: serial.Serial, reader: PacketReader, timeout: float = 5.0):
    drain_serial(ser)
    # Step 1: Send 0x4d 0x4e (ignore whether 0x93 is fully framed/valid)
    try:
        ser.write(b"\x4d\x4e")
    except Exception:
        pass
    # Wait a short time for any 0x93 to arrive, but proceed regardless
    reader.wait_for_type(0x93, max(0.1, timeout * 0.3))

    # Step 2: Repeatedly send 0x87 00 00 07 until we receive 0x87 with addr
    end = time.time() + timeout
    while time.time() < end:
        try:
            ser.write(b"\x87\x00\x00\x07")
        except Exception:
            pass
        pkt87 = reader.wait_for_type(0x87, 0.3)
        if pkt87 is not None and len(pkt87) >= 5:
            # Some boards may send minimal frames; guard indexing
            a1 = pkt87[3] if len(pkt87) > 3 else 0
            a2 = pkt87[4] if len(pkt87) > 4 else 0
            if a1 != 0 or a2 != 0:
                return a1, a2
    raise RuntimeError("discovery failed: no 0x87 address frame")


def build_short(cmd: int, addr1: int, addr2: int) -> bytes:
    tosend = bytearray(bytes([cmd]) + addr1.to_bytes(1, 'big') + addr2.to_bytes(1, 'big'))
    tosend.append(checksum(tosend))
    return bytes(tosend)


def parse_hex4(s: str) -> Tuple[int, int]:
    s = s.strip().lower()
    if len(s) != 4 or any(c not in '0123456789abcdef' for c in s):
        raise ValueError("expected 4 hex digits, e.g., 4387 or 8e43")
    return int(s[:2], 16), int(s[2:], 16)


def main():
    ap = argparse.ArgumentParser(description="Minimal Centaur probe: one command + optional notice-triggered poll")
    ap.add_argument("--port", default="/dev/serial0", help="Serial device (e.g., /dev/serial0)")
    ap.add_argument("--baud", type=int, default=1000000, help="Baud rate")
    ap.add_argument("--send", required=True, help="HEXHEX: send byte + expected type (e.g., 4387)")
    ap.add_argument("--on-notice", help="HEXHEX: unsolicited type + poll byte to send (e.g., 8e43)")
    ap.add_argument("--timeout", type=float, default=2.0, help="Timeout waiting for expected response")
    ap.add_argument("--listen", type=float, default=0.0, help="Remain listening this many seconds after initial exchange")
    ap.add_argument("--interactive", action="store_true", help="Interactive mode: read commands from stdin while printing incoming bytes/packets")
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, baudrate=args.baud, timeout=0.2)
    except Exception as e:
        print(f"failed to open serial {args.port}@{args.baud}: {e}")
        sys.exit(1)

    reader = PacketReader(ser)
    reader.start()

    try:
        print("attempting discovery...")
        addr1, addr2 = discovery(ser, reader, timeout=5.0)
        print(f"discovered addr1={hex(addr1)} addr2={hex(addr2)}")

        # Configure notice handler if provided
        notice_type = None
        notice_poll = None
        if args.on_notice:
            notice_type, notice_poll = parse_hex4(args.on_notice)

            def on_notice(_pkt):
                if _pkt and _pkt[0] == notice_type:
                    try:
                        pkt = build_short(notice_poll, addr1, addr2)
                        print(f"on-notice: send {notice_poll:02x} -> {hexrow(pkt)}")
                        ser.write(pkt)
                    except Exception as e:
                        print(f"on-notice error: {e}")

            reader.set_notice_handler(on_notice)

        # Helper: perform one send/expect cycle
        def do_send_expect(spec: str):
            try:
                sc, et = parse_hex4(spec)
            except Exception:
                print("input error: expected HEXHEX like 4387")
                return
            pkt = build_short(sc, addr1, addr2)
            print(f"send: {sc:02x} -> {hexrow(pkt)} (expect 0x{et:02x})")
            try:
                ser.write(pkt)
            except Exception as e:
                print(f"send error: {e}")
                return
            resp = reader.wait_for_type(et, args.timeout)
            if resp is None:
                print(f"resp: TIMEOUT (expected 0x{et:02x})")
            else:
                payload = resp[5:-1] if len(resp) >= 6 else b""
                print(f"resp: type=0x{resp[0]:02x} payload={hexrow(payload)}")

        # Interactive mode: read commands while printing bytes/packets
        if args.interactive:
            print("interactive mode. commands:")
            print("  <hex2><hex2>   -> send+expect, e.g., 4387")
            print("  on <hex4>      -> set on-notice rule, e.g., on 8e43")
            print("  off            -> clear on-notice rule")
            print("  q              -> quit")
            while True:
                try:
                    line = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    continue
                if line.lower() in ("q", "quit", "exit"):
                    break
                if line.lower().startswith("on "):
                    try:
                        nt, np = parse_hex4(line[3:].strip())
                        notice_type, notice_poll = nt, np
                        def on_notice2(_pkt):
                            if _pkt and _pkt[0] == notice_type:
                                try:
                                    pkt = build_short(notice_poll, addr1, addr2)
                                    print(f"on-notice: send {notice_poll:02x} -> {hexrow(pkt)}")
                                    ser.write(pkt)
                                except Exception as e:
                                    print(f"on-notice error: {e}")
                        reader.set_notice_handler(on_notice2)
                        print(f"on-notice set: 0x{notice_type:02x} -> send 0x{notice_poll:02x}")
                    except Exception as e:
                        print(f"input error: {e}")
                    continue
                if line.lower() == "off":
                    reader.set_notice_handler(None)
                    print("on-notice cleared")
                    continue
                # Default: treat as send+expect hex4
                do_send_expect(line)
        else:
            # Send initial command and wait for expected response
            do_send_expect(args.send)

            # Optional listen window
            if args.listen and args.listen > 0.0:
                print(f"listening for {args.listen:.2f}s (Ctrl+C to stop)...")
                t0 = time.monotonic()
                while time.monotonic() - t0 < args.listen:
                    time.sleep(0.05)

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


