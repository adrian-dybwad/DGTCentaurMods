#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centaur ASCII board with robust 83-occupancy via learned bit mapping,
plus optional F0 classification (if you have templates + F0→square mapping).

Two modes:
  1) --learn-83-map : learn which BIT in the 83 payload corresponds to which square.
     It guides you: empty board -> place single piece on asked square -> remove -> next square...
     For each step we XOR two 83 payloads to find the toggled bit. Saves map to 83_bit_map.json
  2) Default (draw): use learned 83 map to render ASCII occupancy. If --templates and --f0-map are
     provided, also classify piece types per occupied square.

Requires:
  from DGTCentaurMods.board import board
  from DGTCentaurMods.board.sync_centaur import command
  from DGTCentaurMods.board.logging import log
"""

import argparse, json, os, sys, time
from typing import Dict, List, Tuple, Optional

# Prefer project repo modules if running inside the repo
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

# -------------------- Utilities --------------------

def strip_header(msg: bytes, expect_first: int) -> bytes:
    # 83 / F0 / F4 / B2 packets on Centaur begin with a short header; empirically 5 bytes works.
    if len(msg) >= 5 and msg[0] == expect_first:
        return msg[5:]
    return msg

def to_bits_le(data: bytes) -> List[int]:
    """Expand payload to a list of bits (little-endian per byte: bit0 is LSB)."""
    bits = []
    for b in data:
        for k in range(8):
            bits.append((b >> k) & 1)
    return bits

def from_bits(bits: List[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        v = 0
        for k in range(8):
            if i + k < len(bits) and bits[i+k]:
                v |= (1 << k)
        out.append(v)
    return bytes(out)

def save_json(path: str, obj: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(tmp, path)

def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

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

def prompt_yes_no(msg: str, default_yes: bool = True) -> bool:
    while True:
        ans = input(f"{msg} [{'Y/n' if default_yes else 'y/N'}] ").strip().lower()
        if ans == "" and default_yes: return True
        if ans == "" and not default_yes: return False
        if ans in ("y","yes"): return True
        if ans in ("n","no"): return False
        print("Please answer Y or n.")

# -------------------- Raw device calls --------------------

def get_state_payload() -> bytes:
    resp_state = board.sendCommand(command.DGT_BUS_SEND_STATE)
    return strip_header(resp_state, 0x83)

def get_f0_payload() -> bytes:
    resp_f0 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    return strip_header(resp_f0, 0xF0)

# -------------------- F0 helpers (optional classifier path) --------------------

def split_f0_groups(f0_payload: bytes, sentinel: int = 0x7F) -> List[bytes]:
    out, cur = [], []
    for x in f0_payload:
        if x == sentinel:
            if cur: out.append(bytes(cur)); cur = []
        else:
            cur.append(x)
    if cur: out.append(bytes(cur))
    return out

def classify_group(group: bytes, templates: dict, min_len=20, min_energy=1200) -> str:
    L = len(group); E = sum(group)
    if L < min_len and E < min_energy:
        return "."
    if not templates:
        return "?"
    best, best_d = "?", float("inf")
    for key, stats in templates.items():
        muL, muE = stats.get("non7f_mean"), stats.get("energy_mean")
        sdL = stats.get("non7f_std") or 0.0
        sdE = stats.get("energy_std") or 0.0
        if muL is None or muE is None: continue
        if sdL and sdE:
            d = ((L-muL)/sdL)**2 + ((E-muE)/sdE)**2
        else:
            d = ((L-muL)/10.0)**2 + ((E-muE)/200.0)**2
        if d < best_d:
            best_d = d
            best = key[0].upper()
    return best

# -------------------- 83 OCCUPANCY: learning + decode --------------------

def learn_83_map_one_square(target_square: str, current_map: Dict[str,int]) -> Tuple[Dict[str,int], str]:
    """
    Guide: ensure board EMPTY, capture baseline; place ONE piece on target_square; capture again.
    XOR bitfields to find the toggled bit index; record mapping {square: bit_index}.
    """
    input(f"\nPrepare to map {target_square}: make sure the board is EMPTY, then press Enter...")

    # baseline (empty)
    base_payload = get_state_payload()
    base_bits = to_bits_le(base_payload)

    input("Now place ONE piece on the target square and press Enter...")

    # occupied
    occ_payload = get_state_payload()
    occ_bits = to_bits_le(occ_payload)

    # Pad to same length
    n = max(len(base_bits), len(occ_bits))
    base_bits += [0]*(n - len(base_bits))
    occ_bits  += [0]*(n - len(occ_bits))

    # XOR to find change
    diff = [ (a ^ b) for a,b in zip(base_bits, occ_bits) ]
    idxs = [i for i,b in enumerate(diff) if b]

    if len(idxs) == 1:
        bit_index = idxs[0]
        # Avoid overwriting an existing different mapping without warning
        if target_square in current_map and current_map[target_square] != bit_index:
            msg = f"Square {target_square} already mapped to bit {current_map[target_square]} (kept). Suggested {bit_index}."
        else:
            current_map[target_square] = bit_index
            msg = f"Mapped {target_square} -> bit {bit_index}"
    elif len(idxs) == 0:
        msg = "No bit differences detected. Make sure only ONE piece was added, and it changed occupancy."
    else:
        # More than one bit changed (board noise or filtering). Pick the strongest region if needed.
        msg = f"{len(idxs)} bits changed; try again with a clean add/remove on a stable square."

    return current_map, msg

def decode_occupancy_from_83(bit_map: Dict[str,int]) -> Dict[str,int]:
    """
    Using learned bit_map {square: bit_index}, read 83 payload, expand bits,
    and set occupancy per mapped square. Unmapped squares => 0.
    """
    payload = get_state_payload()
    bits = to_bits_le(payload)
    occ = {}
    for sq, idx in bit_map.items():
        occ[sq] = 1 if idx < len(bits) and bits[idx] else 0
    return occ

# -------------------- Main loop --------------------

def draw_once(args, bit_map, f0_map, templates) -> str:
    # Decode occupancy via learned 83 mapping (if available); else show '?' everywhere
    if bit_map:
        occ = decode_occupancy_from_83(bit_map)
    else:
        occ = {}

    # Optional F0 classification if both mapping and templates provided
    labels: Dict[str,str] = {}
    if bit_map and f0_map and templates:
        f0_groups = split_f0_groups(get_f0_payload(), 0x7F)
        for sq, gidx in f0_map.items():
            if gidx is None or gidx < 0 or gidx >= len(f0_groups):
                continue
            if occ.get(sq, 0) == 1:
                labels[sq] = classify_group(f0_groups[gidx], templates)
            else:
                labels[sq] = "."  # empty square wins over group classification
    else:
        # Occupancy only
        for sq in (bit_map.keys() if bit_map else []):
            labels[sq] = "?" if occ.get(sq,0)==1 else "."

    # Build ASCII drawing in requested orientation
    vis_squares = squares_visual_order(args.orientation)
    assign = {}
    for sq in vis_squares:
        if sq in labels:
            assign[sq] = labels[sq]
        elif sq in occ:
            assign[sq] = "?" if occ[sq] else "."
        else:
            assign[sq] = "?"  # unknown until mapped

    return format_board(assign, args.orientation)

def parse_args():
    ap = argparse.ArgumentParser(description="Centaur ASCII board via learned 83 bit mapping + optional F0 classification.")
    ap.add_argument("--orientation", choices=["white-bottom","black-bottom"], default="white-bottom")
    # 83 bit mapping
    ap.add_argument("--learn-83-map", action="store_true", help="Interactive: map 83 payload bits to squares (one-piece XOR).")
    ap.add_argument("--map83-in", type=str, default="83_bit_map.json", help="Load existing 83 bit map.")
    ap.add_argument("--map83-out", type=str, default="83_bit_map.json", help="Save learned 83 bit map.")
    ap.add_argument("--squares", type=str, default="a1,b1,c1,d1,e1,f1,g1,h1,a2,h2",
                    help="Squares to learn (comma or space separated).")
    # Optional F0 classification (requires separately learned F0->square group map)
    ap.add_argument("--templates", type=str, default="", help="templates_summary.json (optional)")
    ap.add_argument("--f0-map", type=str, default="", help="Existing F0 group map (square->group_index)")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()

    # Load existing maps/templates
    bit_map = load_json(args.map83_in) if os.path.exists(args.map83_in) else {}
    f0_map  = load_json(args.f0_map) if args.f0_map and os.path.exists(args.f0_map) else {}
    templates = load_json(args.templates) if args.templates else {}

    if args.learn_83_map:
        # Normalize target squares
        targets = [t.strip().lower() for chunk in args.squares.split(",") for t in chunk.split()]
        targets = [t for t in targets if len(t)==2 and t[0] in FILES and t[1] in RANKS]
        print("83 mapping wizard: for each prompted square, do:")
        print("  1) Ensure EMPTY board, press Enter.")
        print("  2) Place ONE piece on the prompted square, press Enter.")
        print("  3) Mapping will record the toggled bit.\n")
        for sq in targets:
            bit_map, msg = learn_83_map_one_square(sq, bit_map)
            print(msg)
            save_json(args.map83_out, bit_map)
        print(f"\nSaved 83 bit map with {len(bit_map)} entries to {args.map83_out}.")
        sys.exit(0)

    # Draw loop
    while True:
        try:
            board.printChessState()  # helpful live reading in logs
        except Exception as e:
            log.warning(f"printChessState() failed: {e}")
        try:
            ascii_board = draw_once(args, bit_map, f0_map, templates)
            print("\nDetected board (83-mapped occupancy; '?' means unmapped or unknown type):")
            print(ascii_board)
        except Exception as e:
            print(f"\nERROR: {e}", file=sys.stderr)

        if not prompt_yes_no("\nRedraw after moving pieces?", default_yes=True):
            break
