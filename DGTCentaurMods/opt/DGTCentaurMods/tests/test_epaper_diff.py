#!/usr/bin/env python3
"""
Unit tests for compute_changed_region logic without hardware dependencies.

USAGE:
  cd /home/pi/DGTCentaurMods/DGTCentaurMods/opt
  python3 DGTCentaurMods/tests/test_epaper_diff.py
"""

import sys
import os

# Add the opt folder to Python path (so relative imports work if needed)
sys.path.insert(0, os.path.abspath('.'))

# Copy of compute_changed_region to avoid importing epaper.py (which initializes hardware)
def compute_changed_region(prev_bytes: bytes, curr_bytes: bytes) -> tuple[int, int]:
    if not prev_bytes or not curr_bytes or len(prev_bytes) != len(curr_bytes):
        return 0, 295
    total = len(curr_bytes)
    rs, re = 0, 295
    for i in range(total):
        if prev_bytes[i] != curr_bytes[i]:
            rs = (i // 16) - 1
            break
    for i in range(total - 1, -1, -1):
        if prev_bytes[i] != curr_bytes[i]:
            re = (i // 16) + 1
            break
    if rs < 0:
        rs = 0
    if re > 295:
        re = 295
    if rs >= re:
        return 0, 295
    return rs, re


def expect(name, cond):
    print(("PASS: " if cond else "FAIL: ") + name)
    return cond


def main():
    print("Starting compute_changed_region tests")
    print("=" * 50)

    # Constants
    ROWS = 296
    BYTES_PER_ROW = 16
    TOTAL = ROWS * BYTES_PER_ROW

    # Base buffers
    empty = b''
    a = bytearray([0xFF] * TOTAL)
    b = bytearray([0xFF] * TOTAL)

    results = []

    # 1) Empty previous -> full range
    rs, re = compute_changed_region(empty, bytes(a))
    results.append(expect("empty prev -> full", (rs, re) == (0, 295)))

    # 2) Different lengths -> full range
    rs, re = compute_changed_region(bytes(a), bytes(a[:-1]))
    results.append(expect("different lengths -> full", (rs, re) == (0, 295)))

    # 3) Single-byte change at start
    b[0] = 0x00
    rs, re = compute_changed_region(bytes(a), bytes(b))
    results.append(expect("start change rs==0", rs == 0))
    results.append(expect("start change re in [0..2]", 0 <= re <= 2))

    # 4) Single-byte change at end
    b = bytearray([0xFF] * TOTAL)
    b[-1] = 0x00
    rs, re = compute_changed_region(bytes(a), bytes(b))
    # end index maps to last row; guard adds +1 row but clamped to 295
    results.append(expect("end change rs near end", rs >= 293))
    results.append(expect("end change re==295", re == 295))

    # 5) Middle-row change
    mid_row = 123
    idx = mid_row * BYTES_PER_ROW + 7
    b = bytearray([0xFF] * TOTAL)
    b[idx] = 0x00
    rs, re = compute_changed_region(bytes(a), bytes(b))
    results.append(expect("mid change rs<=mid_row", rs <= mid_row))
    results.append(expect("mid change re>=mid_row", re >= mid_row))

    # 6) No change -> full fallback due to equality path
    rs, re = compute_changed_region(bytes(a), bytes(a))
    results.append(expect("no change -> full due to equality", (rs, re) == (0, 295)))

    print("\nResults: {}/{} tests passed".format(sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())


