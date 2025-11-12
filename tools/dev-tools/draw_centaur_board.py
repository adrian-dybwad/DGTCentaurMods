#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centaur ASCII board: robust occupancy + optional learning-based F0→square mapping + simple classification.

- Always shows square occupancy from STATE(83).
- Optional "learn mapping" mode: with exactly one occupied square, associate the most-changed F0 "bucket"
  with that square; store mapping to f0_square_map.json. Repeat across many squares to complete mapping.
- If mapping exists (and optional templates_summary.json provided), attempt piece classification per square.
- Prompts Y/n to redraw after you move pieces.

Requires:
from DGTCentaurMods.board import board
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.board.logging import log
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Tuple, Optional

# Ensure repo import path
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

# -------------------- Utils --------------------

def strip_header(msg: bytes, expect_first: int) -> bytes:
    if len(msg) >= 5 and msg[0] == expect_first:
        return msg[5:]
    return msg

def squares_grid(orientation: str) -> List[str]:
    # Board print orientation only (not F0 mapping!)
    order = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    for r in ranks:
        for f in FILES:
            order.append(f"{f}{r}")
    return order

def format_board(assignments: Dict[str, str], orientation: str) -> str:
    rows = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    rows.append("    " + " ".join(FILES))
    rows.append("    " + "-" * (len(FILES)*2 - 1))
    for r in ranks:
        line = [assignments.get(f"{f}{r}", ".") for f in FILES]
        rows.append(f"{r} | " + " ".join(line))
    return "\n".join(rows)

def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def save_json(path: str, obj: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(tmp, path)

def prompt_yes_no(msg: str, default_yes: bool = True) -> bool:
    while True:
        ans = input(f"{msg} [{'Y/n' if default_yes else 'y/N'}] ").strip().lower()
        if ans == "" and default_yes: return True
        if ans == "" and not default_yes: return False
        if ans in ("y","yes"): return True
        if ans in ("n","no"): return False
        print("Please answer Y or n.")

# -------------------- F0 handling --------------------

def split_f0_groups(f0_payload: bytes, sentinel: int = 0x7F) -> List[bytes]:
    """
    DGT F0 is NOT 64-per-square. Treat 0x7F as a group separator and keep variable-length groups.
    We'll *learn* which group index maps to which square using one-piece diffs.
    """
    out, cur = [], []
    for x in f0_payload:
        if x == sentinel:
            if cur:
                out.append(bytes(cur)); cur = []
        else:
            cur.append(x)
    if cur: out.append(bytes(cur))
    return out

def bucket_features(b: bytes) -> Tuple[int, int]:
    # Keep it simple: (length, energy)
    return len(b), sum(b)

def vector_diff_energy(a: bytes, b: bytes) -> int:
    # Compare two groups by absolute energy difference
    return abs(sum(a) - sum(b))

# -------------------- STATE(83) occupancy --------------------

def get_state_83() -> List[int]:
    """
    Return 64-length occupancy array (0/1) in **visual order** a8..h1 for white-bottom orientation.
    The 83 payload you've captured is 45 bytes; we only need the occupancy bytes the board prints.
    We'll rely on board.printChessState() + DGT_BUS_SEND_STATE => 83 payload which is already in
    an 8x8 logical order used in your logs. We'll parse and flatten as rank-major (a8..h1).
    """
    resp_state = board.sendCommand(command.DGT_BUS_SEND_STATE)
    payload = strip_header(resp_state, 0x83)
    # In your logs, you print an 8x8 of 0/1; payload is 45 bytes where each byte corresponds to something.
    # Empirically, the last 64 nibbles correspond to the board squares. We'll do a simple approach:
    # Count bytes, and if payload has >=64 bytes we take the last 64. Otherwise we can't decode; fall back to zeros.
    if len(payload) >= 64:
        occ = list(payload[-64:])
    else:
        # Fallback: treat any nonzero as occupied, pad to 64 if needed
        occ = [0]*64
        for i, v in enumerate(payload[:64]):
            occ[i] = 1 if v != 0 else 0
    # Normalize to 0/1
    occ = [1 if x != 0 else 0 for x in occ]
    return occ

def occ_to_assignments(occ: List[int], orientation: str, unknown_char: str = "?") -> Dict[str, str]:
    """
    Return dict of square->char where occupied squares are marked with unknown_char,
    empty squares with '.'; orientation affects only display order.
    """
    sqs = squares_grid(orientation)  # visual order a8..h1 or a1..h8 for drawing only
    if len(occ) != 64:
        occ = (occ + [0]*64)[:64]
    return {sqs[i]: (unknown_char if occ[i] else ".") for i in range(64)}

# -------------------- Learning-based mapping --------------------

def learn_mapping_step(prev_f0_groups: List[bytes],
                       cur_f0_groups: List[bytes],
                       occ_squares_now: List[str],
                       mapping: Dict[str, int]) -> Tuple[Dict[str,int], str]:
    """
    If exactly one occupied square exists, find the MOST CHANGED F0 group vs previous snapshot
    and bind that group_index -> square (if not already bound).
    Return (possibly updated mapping, message).
    """
    if len(occ_squares_now) != 1:
        return mapping, "Mapping: need exactly one occupied square to learn (found %d)" % len(occ_squares_now)

    if not prev_f0_groups or not cur_f0_groups:
        return mapping, "Mapping: no previous/cur F0 groups to diff."

    # Compare by energy difference; handle unequal group counts by min length
    n = min(len(prev_f0_groups), len(cur_f0_groups))
    if n == 0:
        return mapping, "Mapping: zero F0 groups to compare."

    diffs = [vector_diff_energy(prev_f0_groups[i], cur_f0_groups[i]) for i in range(n)]
    best_idx = max(range(n), key=lambda i: diffs[i])
    target_sq = occ_squares_now[0]

    # Don’t overwrite an existing mapping unless user wants to; for now overwrite only if unmapped
    if target_sq in mapping and mapping[target_sq] != best_idx:
        return mapping, f"Mapping: square {target_sq} already mapped to group {mapping[target_sq]} (kept). Suggested {best_idx}."

    mapping[target_sq] = best_idx
    return mapping, f"Mapped {target_sq} -> group {best_idx} (Δenergy={diffs[best_idx]})"

# -------------------- Classification --------------------

def classify_from_group(group: bytes, templates: dict, min_len: int, min_energy: int) -> str:
    length = len(group)
    energy = sum(group)
    if length < min_len and energy < min_energy:
        return "."
    if not templates:
        return "?"  # unknown type but occupied
    best_label, best_d = "?", float("inf")
    for key, stats in templates.items():
        mu_len = stats.get("non7f_mean"); mu_eng = stats.get("energy_mean")
        sd_len = stats.get("non7f_std") or 0.0; sd_eng = stats.get("energy_std") or 0.0
        if mu_len is None or mu_eng is None: continue
        if sd_len and sd_eng:
            d = ((length - mu_len)/sd_len)**2 + ((energy - mu_eng)/sd_eng)**2
        else:
            d = ((length - mu_len)/10.0)**2 + ((energy - mu_eng)/200.0)**2
        if d < best_d:
            best_d = d
            best_label = key[0].upper()
    return best_label

# -------------------- Main loop --------------------

def draw_once(args, last_f0_groups, mapping) -> Tuple[str, List[bytes], Dict[str,int]]:
    # STATE 83 occupancy
    resp_state = board.sendCommand(command.DGT_BUS_SEND_STATE)
    s83 = strip_header(resp_state, 0x83)
    # Try to render occupancy robustly
    occ = get_state_83()
    # F0
    resp_f0 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    f0_payload = strip_header(resp_f0, 0xF0)
    groups = split_f0_groups(f0_payload, sentinel=0x7F)

    # Build visual assignments from occupancy first (safe, reliable)
    assignments = occ_to_assignments(occ, args.orientation, unknown_char="?")

    # Optional learning
    if args.learn_map:
        # Which squares are occupied now?
        sqs = squares_grid(args.orientation)  # just for indexing; same visual order as occ list
        occ_squares_now = [sqs[i] for i, v in enumerate(occ) if v]
        mapping, msg = learn_mapping_step(last_f0_groups, groups, occ_squares_now, mapping)
        print(msg)
        if args.map_out:
            save_json(args.map_out, mapping)

    # Optional classification if mapping + templates present
    if args.map_in and os.path.exists(args.map_in):
        mapping = load_json(args.map_in) if not mapping else mapping
    templates = load_json(args.templates) if args.templates else {}

    if mapping and templates:
        # For each mapped square -> group index, classify and write a letter onto that square (if occupied)
        for sq, gi in mapping.items():
            if 0 <= gi < len(groups):
                label = classify_from_group(groups[gi], templates, args.min_len, args.min_energy)
                # Only overwrite if the square is actually occupied per 83
                # If empty but classifier says piece, we’ll trust 83 and leave '.'
                # (avoids ghosting when group changes reflect other board conditions)
                # If occupied but classifier returns '.', show '?' to indicate unknown type
                # otherwise show predicted letter
                # Determine square orientation index to check occupancy:
                grid = squares_grid(args.orientation)
                try:
                    idx = grid.index(sq)
                    if occ[idx]:
                        assignments[sq] = label if label not in (".", "") else "?"
                except ValueError:
                    pass

    # Render ASCII
    ascii_board = format_board(assignments, args.orientation)
    return ascii_board, groups, mapping

def parse_args():
    ap = argparse.ArgumentParser(description="Centaur ASCII board with 83 occupancy + learnable F0 mapping.")
    ap.add_argument("--orientation", choices=["white-bottom","black-bottom"], default="white-bottom")
    ap.add_argument("--templates", type=str, default="", help="templates_summary.json (optional) for piece type classification")
    # Mapping
    ap.add_argument("--learn-map", action="store_true", help="Enable learning: single occupied square binds to most-changed F0 group")
    ap.add_argument("--map-in", type=str, default="", help="Existing mapping file (f0_square_map.json)")
    ap.add_argument("--map-out", type=str, default="f0_square_map.json", help="Where to write learned mapping")
    # Thresholds used in classification only
    ap.add_argument("--min-energy", type=int, default=1200)
    ap.add_argument("--min-len", type=int, default=20)
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    if args.map_in and os.path.exists(args.map_in):
        mapping = load_json(args.map_in)
        print(f"Loaded mapping from {args.map_in} with {len(mapping)} entries.")
    else:
        mapping = {}

    last_groups: List[bytes] = []

    while True:
        try:
            # helpful log of current 83 view
            try:
                board.printChessState()
            except Exception as e:
                log.warning(f"printChessState() failed (continuing): {e}")

            ascii_board, groups, mapping = draw_once(args, last_groups, mapping)
            print("\nDetected board (83 occupancy + optional mapping/classification):")
            print(ascii_board)
            last_groups = groups
        except Exception as e:
            print(f"\nERROR: {e}", file=sys.stderr)

        if not prompt_yes_no("\nRedraw after moving pieces?", default_yes=True):
            break
