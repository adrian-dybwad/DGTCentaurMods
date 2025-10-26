#!/usr/bin/env python3
"""
Standalone DGT Centaur serial probe

Purpose:
  - Discover the Centaur board address
  - Listen for packets and parse them
  - Iterate through known commands and log expected responses
  - Capture and display any unsolicited packets during idle/post-command windows

This script is completely standalone. It does NOT import project-specific
controller modules. It speaks the minimal protocol needed to discover and
exercise commands.

Usage examples:
  python3 tools/dev-tools/centaur_probe.py \
      --port /dev/serial0 --baud 1000000 \
      --idle 15 --timeout 2.0 --post-wait 0.5

Notes:
  - By default, potentially disruptive commands (e.g., sleep) are skipped.
    Use flags to include them if desired.
  - During the idle window, move pieces and press keys to observe whether
    any packets arrive without polling.
"""

import argparse
import sys
import time
import threading
from dataclasses import dataclass
from typing import Optional, List, Tuple

try:
    import serial  # pyserial
except Exception as e:
    print("pyserial is required. pip install pyserial")
    raise


# -----------------------------
# Protocol helpers and constants
# -----------------------------

def hexrow(b: bytes) -> str:
    return ' '.join(f'{x:02x}' for x in b)


def checksum(barr: bytes) -> int:
    csum = 0
    for c in barr:
        csum += c
    return csum % 128


def now_monotonic() -> float:
    return time.monotonic()


# Known response type bytes (packet[0]) used by Centaur
# - 0x85: board changes response (for 0x83)
# - 0xB1: keys / sound / ui acks (for 0x94, sound, etc.)
# - 0xB5: battery info response (for 0x98)
# - 0xF0: snapshot response
# - 0x87: discovery address frame
# - 0x93: discovery ack frame
KNOWN_START_TYPES = {0x85, 0xB1, 0xB5, 0xF0, 0x87, 0x93}


# Discovery raw bytes (no addr/checksum framing)
DGT_DISCOVERY_REQ = b"\x4d\x4e"  # expect 0x93 packet
DGT_DISCOVERY_ACK = b"\x87"       # expect 0x87 packet with addr1/addr2


# Command spec (standalone copy of the subset used in this probe)
@dataclass(frozen=True)
class CommandSpec:
    name: str
    cmd: bytes
    expected_resp_type: Optional[int]
    default_data: Optional[bytes] = None
    disruptive: bool = False  # skip unless explicitly enabled
    full_header: bool = False # if True, cmd is header with 0x00 and length


PROBE_COMMANDS: List[CommandSpec] = [
    # Snapshot: full header; default data chosen to match length accounting
    CommandSpec("DGT_BUS_SEND_SNAPSHOT", b"\xf0\x00\x07", 0xF0, b"\x7f", False, True),

    # Board piece changes: short bus command (no length field)
    CommandSpec("DGT_BUS_SEND_CHANGES", b"\x83", 0x85, None, False, False),

    # Button/key polling: short bus command
    CommandSpec("DGT_BUS_POLL_KEYS", b"\x94", 0xB1, None, False, False),

    # Battery info: short bus command, response 0xB5
    CommandSpec("DGT_SEND_BATTERY_INFO", b"\x98", 0xB5, None, False, False),

    # Sound commands (full headers)
    # Treat sound as fire-and-forget (no guaranteed ack observed on Centaur)
    CommandSpec("SOUND_GENERAL",    b"\xb1\x00\x08", None, b"\x4c\x08", False, True),
    CommandSpec("SOUND_FACTORY",    b"\xb1\x00\x08", None, b"\x4c\x40", False, True),
    CommandSpec("SOUND_POWER_OFF",  b"\xb1\x00\x0a", None, b"\x4c\x08\x48\x08", False, True),
    CommandSpec("SOUND_POWER_ON",   b"\xb1\x00\x0a", None, b"\x48\x08\x4c\x08", False, True),
    CommandSpec("SOUND_WRONG",      b"\xb1\x00\x0a", None, b"\x4e\x0c\x48\x10", False, True),
    CommandSpec("SOUND_WRONG_MOVE", b"\xb1\x00\x08", None, b"\x48\x08", False, True),

    # Sleep (disruptive) - requires explicit flag to include
    CommandSpec("DGT_SLEEP", b"\xb2\x00\x07", 0xB1, b"\x0a", True, True),
]


# -----------------------------
# Packet reader and parser
# -----------------------------

class PacketReader:
    """
    Background reader that accumulates bytes from serial and emits
    complete packets when checksum/length validate.

    Packet format (typical):
        [type] [0x00] [len] [addr1] [addr2] [payload...] [checksum]

    For bus commands, responses still follow this general format; we rely on
    KNOWN_START_TYPES to identify candidate starts and the length at index 2.
    """

    def __init__(self, ser: serial.Serial):
        self.ser = ser
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        # All parsed packets logged here: (ts, packet_bytes)
        self.log: List[Tuple[float, bytes]] = []
        # Queue-like list for consumers; consumed by pop(0)
        self._inbox: List[Tuple[float, bytes]] = []
        self._cv = threading.Condition()

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
                # Print every byte as it is received
                try:
                    print(f"raw byte: {b[0]:02x}")
                except Exception:
                    pass
                self._append_byte(b[0])
            except Exception:
                # Keep trying unless asked to stop
                time.sleep(0.01)

    def _append_byte(self, byte_val: int):
        with self._lock:
            self._buf.append(byte_val)
            # Try to find complete packet(s)
            self._scan_for_packets()

    def _scan_for_packets(self):
        # Attempt parsing from each candidate start index where type is known
        i = 0
        while i < len(self._buf):
            t = self._buf[i]
            if t not in KNOWN_START_TYPES:
                i += 1
                continue

            # Need at least 3 bytes for type, 0x00, length
            if i + 3 > len(self._buf):
                break

            # Length is at i+2; require there is a 0x00 at i+1 for framed packets
            # Some types may not strictly require 0x00, but Centaur responses observed do.
            pkt_len = self._buf[i + 2]
            total_needed = i + pkt_len
            if total_needed > len(self._buf):
                # Not enough bytes yet
                break

            # Verify checksum: sum of all bytes except last mod 128 equals last byte
            pkt = bytes(self._buf[i:total_needed])
            calc = checksum(pkt[:-1])
            if calc != pkt[-1]:
                # Not a valid packet at this offset; advance 1
                i += 1
                continue

            # Valid packet: commit it
            ts = now_monotonic()
            with self._cv:
                self.log.append((ts, pkt))
                self._inbox.append((ts, pkt))
                self._cv.notify_all()
            # Print raw packet bytes as received
            try:
                print(f"raw packet: {hexrow(pkt)}")
            except Exception:
                pass

            # Drop consumed bytes up to total_needed
            del self._buf[:total_needed]
            # Restart from buffer head
            i = 0

    def get_all_since(self, t0: float) -> List[Tuple[float, bytes]]:
        with self._lock:
            return [x for x in self.log if x[0] >= t0]

    def wait_for_type(self, type_byte: int, timeout: float) -> Optional[bytes]:
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            with self._cv:
                # Drain any matching from inbox
                for idx, (ts, pkt) in enumerate(self._inbox):
                    if pkt and pkt[0] == type_byte:
                        self._inbox.pop(idx)
                        return pkt
                self._cv.wait(timeout=min(0.1, max(0.0, remaining)))

    def wait_for_any_since(self, t0: float, timeout: float) -> Optional[bytes]:
        """
        Wait for the first packet whose timestamp is >= t0. Returns the packet bytes or None on timeout.
        """
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            with self._cv:
                # Find first packet at/after t0
                for idx, (ts, pkt) in enumerate(self._inbox):
                    if ts >= t0:
                        self._inbox.pop(idx)
                        return pkt
                self._cv.wait(timeout=min(0.1, max(0.0, remaining)))


# -----------------------------
# Serial utilities
# -----------------------------

def drain_serial(ser: serial.Serial):
    try:
        ser.reset_input_buffer()
    except Exception:
        try:
            n = getattr(ser, 'in_waiting', 0) or 0
            if n:
                ser.read(n)
        except Exception:
            # best-effort drain
            try:
                ser.read(8192)
            except Exception:
                pass


def send_discovery(ser: serial.Serial, reader: PacketReader, timeout: float = 5.0) -> Tuple[int, int]:
    """
    Perform robust discovery using two strategies:
      Preferred:
        1) send 0x4d 0x4e and wait up to timeout/2 for a 0x93 packet
        2) send 0x87 and wait up to timeout/2 for a 0x87 packet; parse addr1, addr2

      Fallback (mirrors tools/dev-tools/serial/poll-board.py behavior):
        - Repeatedly send 0x87 00 00 07 and wait for a 0x87 packet

    Returns (addr1, addr2) on success; raises RuntimeError on failure.
    """
    drain_serial(ser)

    # Attempt standard discovery sequence
    try:
        # Step 1: discovery request
        ser.write(DGT_DISCOVERY_REQ)
        time.sleep(0.01)
        pkt93 = reader.wait_for_type(0x93, max(0.1, timeout * 0.5))
        if pkt93 is not None:
            # Step 2: discovery ack
            ser.write(DGT_DISCOVERY_ACK)
            pkt87 = reader.wait_for_type(0x87, max(0.1, timeout * 0.5))
            if pkt87 is not None and len(pkt87) >= 6:
                return (pkt87[3], pkt87[4])
    except Exception:
        # Fall through to fallback
        pass

    # Fallback: spam 0x87 00 00 07 and look for 0x87 address frame
    end = time.time() + timeout
    while time.time() < end:
        try:
            ser.write(b"\x87\x00\x00\x07")
        except Exception:
            pass
        pkt87 = reader.wait_for_type(0x87, 0.3)
        if pkt87 is not None and len(pkt87) >= 6:
            return (pkt87[3], pkt87[4])

    raise RuntimeError("Discovery failed: no 0x93/0x87 response received")


def build_packet(cmd: bytes, addr1: int, addr2: int, data: Optional[bytes], full_header: bool) -> bytes:
    """
    Build a complete outbound packet.

    Two formats are supported:
    - Short bus command: cmd is 1 byte (e.g., 0x83); packet is:
        [cmd] [addr1] [addr2] [data...] [checksum]

    - Full header command: cmd is a 3+ byte header with 0x00 and length at byte 2
      (e.g., b"b1 00 08"). Packet is:
        [cmd...] [addr1] [addr2] [data...] [checksum]
      The length byte is recomputed to match the final size.
    """
    data = data or b""
    if full_header:
        tosend = bytearray(cmd + addr1.to_bytes(1, 'big') + addr2.to_bytes(1, 'big') + data)
        # Fix length field (3rd byte) to include checksum that will be appended
        tosend[2] = len(tosend) + 1
        tosend.append(checksum(tosend))
        return bytes(tosend)
    else:
        tosend = bytearray(cmd + addr1.to_bytes(1, 'big') + addr2.to_bytes(1, 'big') + data)
        tosend.append(checksum(tosend))
        return bytes(tosend)


def send_and_wait(ser: serial.Serial, reader: PacketReader, spec: CommandSpec, addr1: int, addr2: int, timeout: float) -> Tuple[Optional[bytes], List[bytes]]:
    """
    Send a command and wait for its expected response type (if any).
    Also capture any extra packets that arrive within 'post' window (handled by caller).
    Returns (matching_packet_payload or None, extras list captured later by caller filtering).
    """
    pkt = build_packet(spec.cmd, addr1, addr2, spec.default_data or b"", spec.full_header)
    t0 = now_monotonic()
    ser.write(pkt)

    payload = None
    # Prefer matching type when known; otherwise accept any first packet
    resp = None
    if spec.expected_resp_type is not None:
        resp = reader.wait_for_type(spec.expected_resp_type, timeout)
        if resp is None:
            resp = reader.wait_for_any_since(t0, max(0.0, timeout))
    else:
        resp = reader.wait_for_any_since(t0, max(0.0, timeout))

    if resp is not None:
        # payload is after addr2 up to checksum
        if len(resp) >= 6:
            payload = resp[5:-1]
        else:
            payload = b""
    return (payload, [resp] if resp is not None else [])


# -----------------------------
# Probe workflows
# -----------------------------

def idle_listen(reader: PacketReader, seconds: float):
    print(f"\n=== Idle listen for {seconds:.1f}s ===")
    t0 = now_monotonic()
    time.sleep(seconds)
    seen = reader.get_all_since(t0)
    if seen:
        print(f"observed {len(seen)} packet(s) during idle:")
        for _, pkt in seen:
            # Print type + payload (after addr2 up to checksum)
            payload = pkt[5:-1] if len(pkt) >= 6 else b""
            print(f"  pkt=0x{pkt[0]:02x} payload={hexrow(payload)}")
    else:
        print("no packets observed during idle window")


def iterate_commands(ser: serial.Serial, reader: PacketReader, addr1: int, addr2: int, per_cmd_timeout: float, ack_wait: float, post_wait: float, include_disruptive: bool):
    print("\n=== Command Sweep ===")
    # Deterministic order: by command bytes then by name
    cmds = sorted(PROBE_COMMANDS, key=lambda s: (s.cmd, s.name))
    for spec in cmds:
        if spec.disruptive and not include_disruptive:
            continue

        print(f"\n-- {spec.name} --")
        pkt = build_packet(spec.cmd, addr1, addr2, spec.default_data or b"", spec.full_header)
        print(f"send: {hexrow(pkt)}")

        t0 = now_monotonic()
        try:
            payload, primaries = send_and_wait(ser, reader, spec, addr1, addr2, per_cmd_timeout)
            if spec.expected_resp_type is None:
                print("resp: (no expected type)")
            elif payload is None:
                print(f"resp: TIMEOUT (expected type=0x{spec.expected_resp_type:02x})")
            else:
                # If we received a primary packet, label it as EXPECTED/UNEXPECTED
                if primaries:
                    pkt = primaries[0]
                    label = "EXPECTED" if pkt[0] == spec.expected_resp_type else "UNEXPECTED"
                    print(f"resp: {label} type=0x{pkt[0]:02x} payload={hexrow(payload)}")
                else:
                    print(f"resp: type=0x{spec.expected_resp_type:02x} payload={hexrow(payload)}")
        except Exception as e:
            print(f"resp: ERROR {e}")

        # Ack window: print ANY packets observed shortly after send
        time.sleep(max(0.0, ack_wait))
        ack_end = now_monotonic()
        observed = reader.get_all_since(t0)
        acks = [pkt for (ts, pkt) in observed if ts <= ack_end]
        if acks:
            print(f"ack window packets ({len(acks)}):")
            for pkt in acks:
                payload = pkt[5:-1] if len(pkt) >= 6 else b""
                print(f"  pkt=0x{pkt[0]:02x} payload={hexrow(payload)}")
        else:
            print("ack window: none")

        # Post-wait: any packets after ack window
        time.sleep(max(0.0, post_wait))
        extras = [pkt for (ts, pkt) in reader.get_all_since(ack_end)]
        if extras:
            print(f"post window packets ({len(extras)}):")
            for pkt in extras:
                payload = pkt[5:-1] if len(pkt) >= 6 else b""
                print(f"  pkt=0x{pkt[0]:02x} payload={hexrow(payload)}")
        else:
            print("post window: none")


# -----------------------------
# Hex range sweep (0x40 - 0x55)
# -----------------------------

DISRUPTIVE_CODES = {0x40}  # DGT_SEND_RESET

def iterate_hex_range(ser: serial.Serial, reader: PacketReader, addr1: int, addr2: int, start_code: int, end_code: int, post_wait: float, include_disruptive: bool):
    print(f"\n=== Hex Range Sweep 0x{start_code:02x}..0x{end_code:02x} ===")
    for code in range(start_code, end_code + 1):
        if code in DISRUPTIVE_CODES and not include_disruptive:
            continue
        name = f"CMD_0x{code:02x}"
        cmd = bytes([code])
        pkt = build_packet(cmd, addr1, addr2, b"", False)
        print(f"\n-- {name} --")
        print(f"send: {hexrow(pkt)}")
        t0 = now_monotonic()
        try:
            ser.write(pkt)
        except Exception as e:
            print(f"send error: {e}")
            continue
        # Wait for first packet after send and label EXPECTED/UNEXPECTED
        first = reader.wait_for_any_since(t0, max(0.0, post_wait))
        if first is not None:
            # No expected type for sweep; treat all as UNEXPECTED to highlight
            payload = first[5:-1] if len(first) >= 6 else b""
            print(f"resp: UNEXPECTED type=0x{first[0]:02x} payload={hexrow(payload)}")
            # Print any additional packets also
            extras = [pkt for (_ts, pkt) in reader.get_all_since(t0)]
            for pkt in extras:
                if pkt is first:
                    continue
                payload = pkt[5:-1] if len(pkt) >= 6 else b""
                print(f"  extra: type=0x{pkt[0]:02x} payload={hexrow(payload)}")
        else:
            print("no packets observed")

# -----------------------------
# Update-BRD push-listen helper
# -----------------------------

def send_update_brd_and_listen(ser: serial.Serial, reader: PacketReader, addr1: int, addr2: int, seconds: float):
    print("\n=== Send DGT_SEND_UPDATE_BRD (0x44) and listen ===")
    pkt = build_packet(b"\x44", addr1, addr2, b"", False)
    print(f"send: {hexrow(pkt)}")
    t0 = now_monotonic()
    try:
        ser.write(pkt)
    except Exception as e:
        print(f"send error: {e}")
        return
    # Listen for unsolicited updates while user moves pieces
    time.sleep(max(0.0, seconds))
    seen = reader.get_all_since(t0)
    print(f"observed {len(seen)} packet(s) after 0x44:")
    for _, pkt in seen:
        payload = pkt[5:-1] if len(pkt) >= 6 else b""
        print(f"  pkt=0x{pkt[0]:02x} payload={hexrow(payload)}")

# -----------------------------
# Main
# -----------------------------

def main():
    ap = argparse.ArgumentParser(description="Standalone DGT Centaur serial probe (no project imports)")
    ap.add_argument("--port", default="/dev/serial0", help="Serial device (e.g., /dev/serial0 or /dev/ttyS0)")
    ap.add_argument("--baud", type=int, default=1000000, help="Baud rate")
    ap.add_argument("--idle", type=float, default=10.0, help="Seconds to listen idle before command sweep")
    ap.add_argument("--timeout", type=float, default=1.5, help="Per-command response timeout (seconds)")
    ap.add_argument("--ack-wait", type=float, default=0.15, help="Immediate ack capture window (seconds)")
    ap.add_argument("--post-wait", type=float, default=0.3, help="Post-command extra capture window (seconds)")
    ap.add_argument("--include-disruptive", action="store_true", help="Include disruptive commands (e.g., reset, sleep)")
    ap.add_argument("--sweep", help="Hex sweep range as 4 hex digits, e.g., 4055 for 0x40..0x55")
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, baudrate=args.baud, timeout=0.2)
    except Exception as e:
        print(f"Failed to open serial {args.port} @ {args.baud}: {e}")
        sys.exit(1)

    reader = PacketReader(ser)
    reader.start()

    try:
        print("attempting discovery...")
        addr1, addr2 = send_discovery(ser, reader, timeout=5.0)
        print(f"discovered addr1={hex(addr1)} addr2={hex(addr2)}")

        if args.sweep:
            rng = args.sweep.strip().lower()
            if len(rng) != 4 or any(c not in '0123456789abcdef' for c in rng):
                print(f"Invalid --sweep value '{args.sweep}'. Expected 4 hex digits like 4055.")
            else:
                start = int(rng[:2], 16)
                end = int(rng[2:], 16)
                if start > end:
                    start, end = end, start
                iterate_hex_range(ser, reader, addr1, addr2, start, end, post_wait=args.post_wait, include_disruptive=args.include_disruptive)
        else:
            print("\nReady. Move pieces and press keys during the idle window to test for unsolicited packets.")
            idle_listen(reader, args.idle)
            iterate_commands(ser, reader, addr1, addr2, per_cmd_timeout=args.timeout, ack_wait=args.ack_wait, post_wait=args.post_wait, include_disruptive=args.include_disruptive)
            # Convenience: give an option to immediately test update-brd push
            try:
                send_update_brd_and_listen(ser, reader, addr1, addr2, seconds=max(args.post_wait, 1.0))
            except Exception:
                pass
        print("\nDone.")
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


