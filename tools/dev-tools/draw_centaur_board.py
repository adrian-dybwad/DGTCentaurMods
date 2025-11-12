#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centaur ASCII board using reliable 83 layout (raw a8→h1, flip rows to chess order).
Optionally overlays piece letters if you also supply F0 templates + an f0 square-map.

Usage:
  python draw_centaur_board.py
  python draw_centaur_board.py --templates templates_summary.json --f0-map f0_square_map.json
"""

import argparse, json, os, sys
from typing import Dict, List, Optional, Tuple

# Prefer repo code first
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

# ---------- helpers ----------

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

def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

# ---------- 83 → chess order (reliable occupancy) ----------

def get_chess_state_from_module() -> Optional[List[int]]:
    """
    If your board module exposes getChessState(), use it directly.
    Falls back to None if not available.
    """
    try:
        # Many of your logs already use board.printChessState(); often getChessState() exists too.
        return list(board.getChessState())  # 64 ints, chess order 0=a1 .. 63=h8
    except Exception:
        return None

def get_chess_state_from_raw() -> Optional[List[int]]:
    """
    Fallback: if getChessState() isn't available, grab the raw 64-element board state
    (a8..h1) and flip the rows to chess order (a1..h8), per your mapping.

    NOTE: This assumes your board module provides getBoardState() with 64 entries.
    """
    try:
        raw = list(board.getBoardState())   # 64 ints, raw a8..h1
    except Exception:
        return None
    if len(raw) != 64:
        return None
    chess = [0]*64
    for i in range(64):
        raw_row = i // 8
        raw_col = i % 8
        chess_row = 7 - raw_row   # invert rows
        chess_col = raw_col
        chess_idx = chess_row*8 + chess_col
        chess[chess_idx] = raw[i]
    return chess

def get_occupancy_chess_order() -> List[int]:
    """
    Returns a 64-int list (0/1) in chess order (a1..h8).
    Tries getChessState() first, then raw→chess flip fallback.
    """
    st = get_chess_state_from_module()
    if st is None:
        st = get_chess_state_from_raw()
    if st is None or len(st) != 64:
        # last resort: call printChessState() for your logs and return all zeros
        try:
            board.printChessState()
        except Exception:
            pass
        return [0]*64
    # Normalize to 0/1
    return [1 if int(x) != 0 else 0 for x in st]

# ---------- optional F0 overlay ----------

def strip_header(msg: bytes, expect_first: int) -> bytes:
    if len(msg) >= 5 and msg[0] == expect_first:
        return msg[5:]
    return msg

def split_f0_groups(f0_payload: bytes, sentinel: int = 0x7F) -> List[bytes]:
    out, cur = [], []
    for x in f0_payload:
        if x == sentinel:
            if cur: out.append(bytes(cur)); cur = []
        else:
            cur.append(x)
    if cur: out.append(bytes(cur))
    return out

def classify_group(group: bytes, stats: dict, min_len=20, min_energy=1200) -> str:
    L = len(group); E = sum(group)
    if L < min_len and E < min_energy:
        return "."
    if not stats:
        return "?"
    best, best_d = "?", float("inf")
    for key, s in stats.items():
        muL, muE = s.get("non7f_mean"), s.get("energy_mean")
        sdL = s.get("non7f_std") or 0.0
        sdE = s.get("energy_std") or 0.0
        if muL is None or muE is None: continue
        if sdL and sdE:
            d = ((L-muL)/sdL)**2 + ((E-muE)/sdE)**2
        else:
            d = ((L-muL)/10.0)**2 + ((E-muE)/200.0)**2
        if d < best_d:
            best_d = d
            best = key[0].upper()
    return best

def try_overlay_f0_letters(assign: Dict[str,str],
                           orientation: str,
                           templates_path: Optional[str],
                           f0_map_path: Optional[str]) -> None:
    """
    If both templates and an f0 square map exist, overlay letters on occupied squares.
    f0_map: { "a1": group_index, ... }
    """
    if not templates_path or not f0_map_path:
        return
    templates = load_json(templates_path)
    f0_map = load_json(f0_map_path)
    if not templates or not f0_map:
        return

    # Capture F0 once
    resp_f0 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    f0 = strip_header(resp_f0, 0xF0)
    groups = split_f0_groups(f0, 0x7F)

    # Only overlay on squares we already marked as occupied ('.' vs '?')
    for sq, gi in f0_map.items():
        if not isinstance(gi, int) or gi < 0 or gi >= len(groups):
            continue
        if assign.get(sq) in (".",):  # empty stays empty
            continue
        label = classify_group(groups[gi], templates)
        if label not in (".", ""):
            assign[sq] = label
        else:
            # occupied but unknown type
            assign[sq] = "?"

# ---------- main loop ----------

def main():
    ap = argparse.ArgumentParser(description="ASCII board via reliable 83 layout + optional F0 overlay.")
    ap.add_argument("--orientation", choices=["white-bottom","black-bottom"], default="white-bottom")
    ap.add_argument("--templates", type=str, default="", help="templates_summary.json (optional)")
    ap.add_argument("--f0-map",   type=str, default="", help="square→group_index JSON (optional)")
    args = ap.parse_args()

    while True:
        try:
            # Reliable occupancy
            occ = get_occupancy_chess_order()  # 64 ints, chess order a1..h8
            # Build assignments from occupancy
            assign: Dict[str,str] = {}
            vis = squares_visual_order(args.orientation)
            # vis is in rank-8→1 order for white-bottom (display order);
            # our occ list is in chess order a1..h8 (index 0 is a1).
            # Fill by coordinates directly:
            for sq in vis:
                f, r = sq[0], int(sq[1])
                file_idx = FILES.index(f)
                rank_idx = r - 1
                idx = rank_idx * 8 + file_idx  # chess order a1..h8
                assign[sq] = "?" if occ[idx] else "."

            # Optional: overlay piece letters using F0
            try_overlay_f0_letters(assign, args.orientation, args.templates or None, args.f0_map or None)

            # Print board
            try:
                board.printChessState()  # also show your module’s 0/1 matrix in logs
            except Exception:
                pass
            print("\nDetected board (83-based occupancy; '?'=occupied, '.'=empty):")
            print(format_board(assign, args.orientation))
        except Exception as e:
            print(f"\nERROR: {e}", file=sys.stderr)

        if not prompt_yes_no("\nRedraw after moving pieces?", default_yes=True):
            break

if __name__ == "__main__":
    main()
