#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centaur ASCII board using:
 - Reliable 83 occupancy (a8→h1 raw -> flip rows -> chess a1→h8)
 - F0 parsed as 64 sequential big-endian uint16 values in the SAME raw order as 83.

What it does now:
 - Prints occupancy from 83 ('?' = occupied, '.' = empty)
 - Optionally also prints a compact per-square F0 table (--show-f0)
 - Stub hook for future per-piece classification using THIS F0 format

Usage examples:
  python draw_centaur_board.py
  python draw_centaur_board.py --show-f0
  python draw_centaur_board.py --orientation black-bottom
"""

import argparse, os, sys
from typing import Dict, List, Optional, Tuple

# Prefer repo path first (adjust if needed)
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'DGTCentaurMods', 'opt'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception:
    pass

from DGTCentaurMods.board import board
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.board.logging import log

FILES = "abcdefgh"
RANKS = "12345678"

# -------------------- Basics --------------------

def prompt_yes_no(msg: str, default_yes: bool = True) -> bool:
    while True:
        ans = input(f"{msg} [{'Y/n' if default_yes else 'y/N'}] ").strip().lower()
        if ans == "" and default_yes: return True
        if ans == "" and not default_yes: return False
        if ans in ("y","yes"): return True
        if ans in ("n","no"): return False
        print("Please answer Y or n.")

def squares_visual_order(orientation: str) -> List[str]:
    order = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    for r in ranks:
        for f in FILES:
            order.append(f"{f}{r}")
    return order

def format_board(assignments: Dict[str,str], orientation: str) -> str:
    lines = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    lines.append("    " + " ".join(FILES))
    lines.append("    " + "-" * (len(FILES)*2 - 1))
    for r in ranks:
        row = [assignments.get(f"{f}{r}", ".") for f in FILES]
        lines.append(f"{r} | " + " ".join(row))
    return "\n".join(lines)

def strip_header(msg: bytes, expect_first: int) -> bytes:
    # Centaur packets usually have a small header (5 bytes in our earlier captures).
    if len(msg) >= 5 and msg[0] == expect_first:
        return msg[5:]
    return msg

# -------------------- 83 -> chess order (reliable occupancy) --------------------

def get_chess_state_from_module() -> Optional[List[int]]:
    try:
        st = list(board.getChessState())  # already chess order a1..h8
        return [1 if int(x)!=0 else 0 for x in st]
    except Exception:
        return None

def get_chess_state_from_raw() -> Optional[List[int]]:
    """
    Fallback: raw order a8..h1 -> flip vertically -> chess order a1..h8.
    """
    try:
        raw = list(board.getBoardState())  # 64 ints, raw a8..h1
    except Exception:
        return None
    if len(raw) != 64:
        return None
    chess = [0]*64
    for i in range(64):
        raw_row = i // 8
        raw_col = i % 8
        chess_row = 7 - raw_row
        chess_col = raw_col
        chess_idx = chess_row*8 + chess_col
        chess[chess_idx] = 1 if int(raw[i]) != 0 else 0
    return chess

def get_occupancy_chess_order() -> List[int]:
    st = get_chess_state_from_module()
    if st is None:
        st = get_chess_state_from_raw()
    if st is None or len(st) != 64:
        try:
            board.printChessState()
        except Exception:
            pass
        return [0]*64
    return st

# -------------------- F0 (sequential 64x uint16) --------------------

def get_f0_u16_raw_a8h1() -> Optional[List[int]]:
    """
    Parse F0 as 64 sequential BE uint16 values in RAW order (a8..h1).
    This mirrors your legacy serial code: val = hi*256 + lo.
    """
    try:
        resp_f0 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    except Exception as e:
        log.error(f"F0 read failed: {e}")
        return None
    payload = strip_header(resp_f0, 0xF0)

    # We expect at least 128 bytes for 64 BE uint16 values.
    # If longer (extra trailer), take the first 128.
    if len(payload) < 128:
        # Some firmwares may include different leading/trailing bytes; try to find a 128-byte window.
        # Fallback: abort cleanly.
        log.warning(f"F0 payload too short ({len(payload)} bytes), need >=128.")
        return None
    data = payload[:128]

    vals = []
    for i in range(0, 128, 2):
        hi = data[i]
        lo = data[i+1]
        vals.append(hi*256 + lo)
    if len(vals) != 64:
        return None
    return vals  # raw order a8..h1

def f0_to_chess_order(u16_raw: List[int]) -> List[int]:
    """
    Convert raw a8..h1 to chess a1..h8 (same row flip as 83).
    """
    chess = [0]*64
    for i in range(64):
        raw_row = i // 8
        raw_col = i % 8
        chess_row = 7 - raw_row
        chess_col = raw_col
        chess_idx = chess_row*8 + chess_col
        chess[chess_idx] = u16_raw[i]
    return chess

def format_f0_table(f0_chess: List[int], orientation: str, width: int = 5) -> str:
    """
    Pretty print F0 per square as small integers, same board orientation.
    """
    lines = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    header = "    " + " ".join([f"{f:>{width}}" for f in FILES])
    lines.append(header)
    lines.append("    " + "-" * (len(FILES)*(width+1)-1))
    for r in ranks:
        row_vals = []
        for f in FILES:
            idx = (int(r)-1)*8 + FILES.index(f)  # chess order
            row_vals.append(f"{f0_chess[idx]:>{width}}")
        lines.append(f"{r} | " + " ".join(row_vals))
    return "\n".join(lines)

# -------------------- (Future) piece letters stub --------------------

def overlay_piece_letters(assign: Dict[str,str], f0_chess: Optional[List[int]]) -> None:
    """
    Placeholder: if you want quick letters via simple thresholds, add them here.
    For now we leave '?' for occupied squares until we record templates in THIS format.
    """
    _ = (assign, f0_chess)
    # Example (disabled):
    # if f0_chess and some_threshold_logic:
    #     assign[sq] = 'P' / 'N' / ...

# -------------------- draw loop --------------------

def draw_once(orientation: str, show_f0: bool) -> str:
    # 83 occupancy (reliable)
    occ = get_occupancy_chess_order()  # chess order a1..h8

    # Build ASCII occupancy
    vis = squares_visual_order(orientation)
    assign: Dict[str,str] = {}
    for sq in vis:
        f, r = sq[0], int(sq[1])
        idx = (r - 1) * 8 + FILES.index(f)
        assign[sq] = "?" if occ[idx] else "."

    # Optional F0 table
    f0_table = ""
    if show_f0:
        u16_raw = get_f0_u16_raw_a8h1()
        if u16_raw:
            f0_chess = f0_to_chess_order(u16_raw)
            overlay_piece_letters(assign, f0_chess)  # currently a stub
            f0_table = "\n\nF0 per-square (uint16):\n" + format_f0_table(f0_chess, orientation)
        else:
            f0_table = "\n\nF0 per-square (uint16): [unavailable]"

    try:
        board.printChessState()  # also writes your module’s grid to logs
    except Exception:
        pass

    return "Detected board (83→'?' occupied, '.' empty):\n" + format_board(assign, orientation) + f0_table

def parse_args():
    ap = argparse.ArgumentParser(description="ASCII board using 83 occupancy + sequential F0 (64x uint16).")
    ap.add_argument("--orientation", choices=["white-bottom","black-bottom"], default="white-bottom")
    ap.add_argument("--show-f0", action="store_true", help="Print per-square F0 uint16 values.")
    return ap.parse_args()

def main():
    args = parse_args()
    while True:
        try:
            out = draw_once(args.orientation, args.show_f0)
            print("\n" + out)
        except Exception as e:
            print(f"\nERROR: {e}", file=sys.stderr)

        if not prompt_yes_no("\nRedraw after moving pieces?", default_yes=True):
            break

if __name__ == "__main__":
    main()
