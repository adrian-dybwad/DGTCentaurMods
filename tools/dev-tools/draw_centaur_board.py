#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Auto-detect piece/position ASCII drawing for DGT Centaur.

- Captures F0 and (optionally) uses precomputed templates_summary.json
  to classify each square as P/N/B/R/Q/K.
- Prints an 8x8 ASCII board.
- Prompts Y/n to redraw so you can move pieces and refresh.

Requirements:
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

# Ensure we import repo code first if you're running from tools/dev-tools/ etc.
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


# -------------------- Helpers --------------------

def strip_header(msg: bytes, expect_first: int) -> bytes:
    """Drop a 5-byte header if present, else return as-is."""
    if len(msg) >= 5 and msg[0] == expect_first:
        return msg[5:]
    return msg

def split_f0_buckets(f0_payload: bytes, sentinel: int = 0x7F) -> List[bytes]:
    """Split F0 by 0x7F into per-square 'buckets' (best effort)."""
    out, cur = [], []
    for x in f0_payload:
        if x == sentinel:
            if cur:
                out.append(bytes(cur))
                cur = []
        else:
            cur.append(x)
    if cur:
        out.append(bytes(cur))
    return out

def bucket_features(b: bytes) -> Tuple[int, int, int]:
    """
    Return simple features for a bucket:
      - count_non7f (== len(b))
      - energy (sum of bytes)
      - nnz (nonzero count)
    """
    length = len(b)
    energy = sum(b)
    nnz = sum(1 for x in b if x != 0)
    return length, energy, nnz

def load_templates(path: Optional[str]) -> Dict[str, Dict[str, float]]:
    """
    Load templates_summary.json (optional).
    Expected shape:
      { "Pw": {"count":N, "non7f_mean":..., "energy_mean":..., ...}, ... }
    We’ll use only means and (if present) stds for a z-score distance.
    """
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            # Normalize keys to just piece letter (ignore color by default)
            norm = {}
            for key, stats in data.items():
                # Key could be "Pw", "Pb", etc — keep both if present, but we don't rely on color.
                norm[key] = stats
            return norm
    except Exception as e:
        log.warning(f"Failed to load templates from {path}: {e}")
        return {}

def squares_order(orientation: str) -> List[str]:
    """
    Return list of squares corresponding to bucket indices.
    We try two conventional orders:
      - 'white-bottom': a8..h8, a7..h7, ..., a1..h1 (top row = 8)
      - 'black-bottom': a1..h1, a2..h2, ..., a8..h8 (top row = 1)
    NOTE: Exact F0 bucket→square mapping is not confirmed; this gives a usable view.
    """
    order = []
    if orientation == "white-bottom":
        ranks = list(reversed(RANKS))  # 8->1
    else:
        ranks = list(RANKS)            # 1->8

    for r in ranks:
        for f in FILES:
            order.append(f"{f}{r}")
    return order

def format_board_ascii(assignments: Dict[str, str], orientation: str) -> str:
    """
    assignments: { 'a1': 'P', 'b1':'N', ... } or '.' for empty, '?' for unknown
    """
    rows = []
    if orientation == "white-bottom":
        ranks = list(reversed(RANKS))  # show rank 8 at top
    else:
        ranks = list(RANKS)            # show rank 1 at top

    header = "    " + " ".join(FILES)
    rows.append(header)
    rows.append("    " + "-" * (len(FILES)*2 - 1))
    for r in ranks:
        row = [assignments.get(f"{f}{r}", ".") for f in FILES]
        rows.append(f"{r} | " + " ".join(row))
    return "\n".join(rows)

def classify_bucket(
    feat: Tuple[int,int,int],
    templates: Dict[str, Dict[str, float]],
    min_energy: int,
    min_len: int,
    use_color: bool = False
) -> str:
    """
    Classify a single bucket from (len, energy, nnz) using nearest centroid.
    - If below presence thresholds (min_energy and min_len), return '.' (empty).
    - If no templates provided, return '?' for "occupied but unknown".
    - If templates available, choose argmin distance among known keys.
      Distance uses z-score if stds exist, else Euclidean in (len, energy).
    """
    length, energy, _nnz = feat

    # Presence check
    if length < min_len and energy < min_energy:
        return '.'

    if not templates:
        return '?'  # occupied but unknown

    # Build candidate set; if use_color=False, consider both white/black as same piece family
    # We'll collapse Pw/Pb -> P, Nw/Nb -> N, etc. by comparing to whichever exists.
    best_label = '?'
    best_dist = float('inf')

    # For robustness, try keys in templates directly (e.g., "Pw","Pb","P", etc.)
    # and also derive unique piece initial from keys to ensure coverage.
    keys = list(templates.keys())
    for key in keys:
        stats = templates[key]
        mu_len = stats.get("non7f_mean")
        mu_eng = stats.get("energy_mean")
        sd_len = stats.get("non7f_std") or 0.0
        sd_eng = stats.get("energy_std") or 0.0

        if mu_len is None or mu_eng is None:
            continue

        # z-score distance if stds are present and >0, else scaled Euclidean
        if sd_len and sd_eng:
            d = ((length - mu_len)/sd_len)**2 + ((energy - mu_eng)/sd_eng)**2
        else:
            # Simple scaling so energy dominates appropriately
            d = ((length - mu_len)/10.0)**2 + ((energy - mu_eng)/200.0)**2

        if d < best_dist:
            best_dist = d
            # Reduce e.g. 'Pw' -> 'P'
            best_label = key[0].upper() if key else '?'

    return best_label if best_label != '?' else '?'

def prompt_yes_no(msg: str, default_yes: bool = True) -> bool:
    while True:
        ans = input(f"{msg} [{'Y/n' if default_yes else 'y/N'}] ").strip().lower()
        if ans == "" and default_yes:
            return True
        if ans == "" and not default_yes:
            return False
        if ans in ("y","yes"): return True
        if ans in ("n","no"): return False
        print("Please answer Y or n.")


# -------------------- Core draw/loop --------------------

def detect_and_draw(templates_path: Optional[str], orientation: str, min_energy: int, min_len: int) -> str:
    """
    Single pass: capture F0, split into buckets, classify each, build ASCII board string.
    Returns the ASCII board string.
    """
    # Optional: show current device state in logs for troubleshooting
    try:
        board.printChessState()
    except Exception as e:
        log.warning(f"printChessState() failed (continuing): {e}")

    # Get F0
    resp_f0 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    log.info(f"F0 raw: {' '.join(f'{b:02x}' for b in resp_f0)}")
    f0_payload = strip_header(resp_f0, 0xF0)

    buckets = split_f0_buckets(f0_payload, sentinel=0x7F)
    n_b = len(buckets)

    # Heuristic: we expect ~64 buckets; if not, warn but continue with min(64, n_b) and pad if needed.
    if n_b != 64:
        log.warning(f"F0 produced {n_b} buckets (expected ~64). Proceeding heuristically.")

    # Load templates (optional)
    templates = load_templates(templates_path)

    # Choose mapping from bucket index -> square
    sq_order = squares_order(orientation)

    # Build per-square assignment
    assignments: Dict[str, str] = {}
    count = min(64, n_b)
    for i in range(count):
        b = buckets[i]
        feat = bucket_features(b)
        label = classify_bucket(feat, templates, min_energy=min_energy, min_len=min_len)
        assignments[sq_order[i]] = label

    # If fewer buckets than squares, fill the rest with '.'
    if count < 64:
        for i in range(count, 64):
            assignments[sq_order[i]] = '.'

    # Render ASCII
    ascii_board = format_board_ascii(assignments, orientation)
    return ascii_board


def main():
    ap = argparse.ArgumentParser(description="Auto-detect and draw DGT Centaur board ASCII from F0.")
    ap.add_argument("--templates", type=str, default="", help="Path to templates_summary.json (optional).")
    ap.add_argument("--orientation", type=str, choices=["white-bottom","black-bottom"], default="white-bottom",
                    help="Board orientation to render (default: white-bottom).")
    ap.add_argument("--min-energy", type=int, default=1200,
                    help="Minimum bucket energy to consider a square occupied (default: 1200).")
    ap.add_argument("--min-len", type=int, default=20,
                    help="Minimum bucket length (non-7F bytes) to consider occupied (default: 20).")
    ap.add_argument("--interval", type=float, default=0.0,
                    help="Optional seconds to sleep before first capture (e.g., allow board to settle).")
    return ap.parse_args(), ap


if __name__ == "__main__":
    args, _ = main()

    if args.interval > 0:
        time.sleep(args.interval)

    while True:
        try:
            ascii_board = detect_and_draw(
                templates_path=args.templates or None,
                orientation=args.orientation,
                min_energy=args.min_energy,
                min_len=args.min_len
            )
            print("\nDetected board:")
            print(ascii_board)
        except Exception as e:
            print(f"\nERROR during detection: {e}", file=sys.stderr)

        if not prompt_yes_no("\nRedraw after moving pieces?", default_yes=True):
            break
