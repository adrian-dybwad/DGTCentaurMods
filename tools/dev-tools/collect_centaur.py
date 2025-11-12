#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centaur F0/F4/96 Data Collector + Interactive Labeling

What this does
--------------
- Guides you through a test plan to collect:
  1) Empty-board baseline
  2) Full starting position
  3) Single-piece labeled captures (rook/knight/bishop/queen/king/pawn on specific squares)
  4) (Optional) Custom FENs you provide via CLI

- For each capture, records:
  * STATE (82 -> 83)
  * F0 (features)
  * F4 (calibration/baseline; persistent)
  * 96 -> b2 (telemetry/counters)
  * Timestamp + label
  * For labeled single-piece captures: piece type and square you placed

- Saves:
  * JSONL: one JSON object per capture with raw hex and derived metrics
  * CSV: compact summary per capture

Usage examples
--------------
  python collect_centaur.py                       # run the guided plan
  python collect_centaur.py --skip-plan --fen "8/8/8/8/8/8/8/8 w - - 0 1"
  python collect_centaur.py --fens my_fens.txt --repeat 2 --label "trial_A"
  python collect_centaur.py --skip-confirm --repeat 3

Requires
--------
from DGTCentaurMods.board import Board
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.board.logging import log
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
from typing import List, Tuple, Dict, Any

# Ensure we import the repo package first (not a system-installed copy)
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'DGTCentaurMods', 'opt'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception:
    pass


from DGTCentaurMods.board import board as Board
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.board.logging import log


# ------------------------- Low-level helpers -------------------------

def bytes_to_hex(b: bytes) -> str:
    return " ".join(f"{x:02x}" for x in b)


def split_f0_buckets(f0_payload: bytes, sentinel: int = 0x7F) -> List[bytes]:
    """
    Split F0 payload into “buckets” separated by 0x7F. This is a pragmatic way to
    summarize features without assuming exact square mapping yet.
    Empty buckets are omitted.
    """
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


def bucket_metrics(b: bytes) -> Tuple[int, int, int]:
    """
    Quick bucket features:
      - length (#bytes)
      - energy (sum of bytes)
      - nnz (non-zero count)
    """
    length = len(b)
    energy = sum(b)
    nnz = sum(1 for x in b if x != 0)
    return length, energy, nnz


def strip_header(msg: bytes, expect_first: int) -> bytes:
    """
    In traces, messages often look like:
      [type][??][id_hi][id_lo]...[payload...]
    where the first 5 bytes are meta. We'll conservatively drop 5 bytes if the
    first byte matches the expected type and len >= 5. Otherwise return as-is.
    """
    if len(msg) >= 5 and msg[0] == expect_first:
        return msg[5:]
    return msg


def ensure_outdir(base_out: str) -> str:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(base_out, f"centaur_capture_{ts}")
    os.makedirs(outdir, exist_ok=True)
    return outdir


def prompt_yes_no(msg: str, default_yes: bool = True) -> bool:
    while True:
        ans = input(f"{msg} [{'Y/n' if default_yes else 'y/N'}] ").strip().lower()
        if ans == "" and default_yes:
            return True
        if ans == "" and not default_yes:
            return False
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please answer Y or n.")


# ------------------------- Board capture -------------------------

def capture_once(board: Board, fen: str, label: str, extra_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute one full capture sequence for a given state.
    Returns a dict containing raw hex and derived stats.
    """
    # STATE (82 -> 83)
    resp_state = board.sendCommand(command.DGT_BUS_SEND_STATE)
    log.info(f"STATE 83: {' '.join(f'{b:02x}' for b in resp_state)}")

    # F0
    resp_f0 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    log.info(f"Discovery: RESPONSE FROM F0 - {' '.join(f'{b:02x}' for b in resp_f0)}")

    # F4
    resp_f4 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F4)
    log.info(f"Discovery: RESPONSE FROM F4 - {' '.join(f'{b:02x}' for b in resp_f4)}")

    # 96 -> b2
    resp_b2 = board.sendCommand(command.DGT_BUS_SEND_96)
    log.info(f"Discovery: RESPONSE FROM 96 - {' '.join(f'{b:02x}' for b in resp_b2)}")

    f0_payload = strip_header(resp_f0, 0xF0)
    f4_payload = strip_header(resp_f4, 0xF4)
    b2_payload = strip_header(resp_b2, 0xB2)
    s83_payload = strip_header(resp_state, 0x83)

    # Derived metrics for F0
    buckets = split_f0_buckets(f0_payload, sentinel=0x7F)
    bucket_stats = [bucket_metrics(b) for b in buckets]
    total_non7f = sum(len(b) for b in buckets)
    total_energy = sum(sum(b) for b in buckets)

    # Occupancy quick stats (we intentionally don't assume square mapping here)
    occupancy_len = len(s83_payload)
    occupancy_nonzero = sum(1 for x in s83_payload if x != 0)

    now = dt.datetime.now().isoformat(timespec="seconds")
    record = {
        "timestamp": now,
        "label": label,
        "fen": fen,
        "meta": extra_meta or {},
        "state_full_hex": bytes_to_hex(resp_state),
        "state_payload_hex": bytes_to_hex(s83_payload),
        "f0_full_hex": bytes_to_hex(resp_f0),
        "f0_payload_hex": bytes_to_hex(f0_payload),
        "f4_full_hex": bytes_to_hex(resp_f4),
        "f4_payload_hex": bytes_to_hex(f4_payload),
        "b2_full_hex": bytes_to_hex(resp_b2),
        "b2_payload_hex": bytes_to_hex(b2_payload),
        "f0_bucket_count": len(buckets),
        "f0_total_non7f_bytes": total_non7f,
        "f0_total_energy": total_energy,
        "f0_bucket_stats": bucket_stats,  # list of (length, energy, nnz)
        "occupancy_payload_len": occupancy_len,
        "occupancy_nonzero_bytes": occupancy_nonzero,
    }
    return record


# ------------------------- Guided plan -------------------------

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
EMPTY_FEN = "8/8/8/8/8/8/8/8 w - - 0 1"

PIECES = ["P", "N", "B", "R", "Q", "K"]  # (white); we’ll record color separately
FILES = "abcdefgh"
RANKS = "12345678"

def valid_square(s: str) -> bool:
    return len(s) == 2 and s[0] in FILES and s[1] in RANKS


def prompt_user_setup(board: Board, title: str, fen: str, instructions: str, skip_confirm: bool) -> bool:
    print("\n==================================================")
    print(f"{title}")
    print(f"Target FEN:\n  {fen}")
    print(f"Instructions:\n  {instructions}")
    try:
        board.printChessState()  # helpful live readout in your logger
    except Exception as e:
        log.warning(f"printChessState() failed (continuing): {e}")

    if skip_confirm:
        return True
    return prompt_yes_no("Ready to capture?", default_yes=True)


def run_guided_plan(board: Board, out_jsonl, out_csv, label: str, repeat: int, skip_confirm: bool):
    """
    A 12-step plan:
      1) Empty board baseline
      2) Full starting position
      3-12) Single-piece labeled captures (white): R,N,B,Q,K,P on specified squares
    Feel free to answer 'n' to skip any step on the fly.
    """
    steps: List[Dict[str, Any]] = []

    # 1) Empty board
    steps.append({
        "title": "Step 1: Empty-board baseline",
        "fen": EMPTY_FEN,
        "instructions": "Remove all pieces from the board.",
        "mode": "guided_fen"
    })

    # 2) Full start position
    steps.append({
        "title": "Step 2: Full starting position",
        "fen": START_FEN,
        "instructions": "Set up the full chess starting position: white on your side (ranks 1-2).",
        "mode": "guided_fen"
    })

    # 3-12) Labeled single-piece captures (white)
    # choose squares spaced apart to reduce bleed; adjust if you prefer others
    labeled_single_piece_plan = [
        ("R", "a1"),
        ("N", "b1"),
        ("B", "c1"),
        ("Q", "d1"),
        ("K", "e1"),
        ("P", "a2"),
        ("P", "d2"),
        ("P", "e2"),
        ("P", "h2"),
        ("B", "f1"),
    ]
    for idx, (p, sq) in enumerate(labeled_single_piece_plan, start=3):
        fen = EMPTY_FEN  # single-piece tests start from empty board
        steps.append({
            "title": f"Step {idx}: Single-piece labeled capture ({p} on {sq})",
            "fen": fen,
            "instructions": f"Place exactly ONE white {piece_name(p)} on {sq}. Leave all other squares empty.",
            "mode": "label_single_piece",
            "piece": p,
            "square": sq,
            "color": "w"
        })

    # Run steps
    cw = csv_writer(out_csv)
    total = 0
    for step in steps:
        title = step["title"]
        fen = step["fen"]
        instructions = step["instructions"]
        mode = step["mode"]

        if not prompt_user_setup(board, title, fen, instructions, skip_confirm):
            print("Skipped.")
            continue

        # For single-piece mode, we’ll re-ask piece/square in case you want to override on the fly
        extra_meta = {"mode": mode}

        if mode == "label_single_piece":
            print(f"Planned piece: {step['piece']} (white), square: {step['square']}")
            if not prompt_yes_no("Use the planned piece/square?", default_yes=True):
                piece = input("Enter piece type [P,N,B,R,Q,K]: ").strip().upper()
                if piece not in PIECES:
                    print("Invalid piece; defaulting to planned.")
                    piece = step["piece"]
                square = input("Enter square (e.g., e4): ").strip().lower()
                if not valid_square(square):
                    print("Invalid square; defaulting to planned.")
                    square = step["square"]
            else:
                piece = step["piece"]
                square = step["square"]

            extra_meta.update({
                "label_piece": piece,
                "label_color": "w",
                "label_square": square
            })
            print(f"→ Recording as: {piece_name(piece)} on {square} (white)")

        # Repeat captures if requested
        for i in range(repeat):
            try:
                rec = capture_once(board, fen, label, extra_meta)
            except Exception as e:
                log.error(f"Capture failed ({title}, attempt {i+1}/{repeat}): {e}")
                continue

            # For single-piece steps, do a sanity check on occupancy
            if mode == "label_single_piece":
                occ_nz = rec.get("occupancy_nonzero_bytes", 0)
                if occ_nz <= 0:
                    print("WARNING: Occupancy suggests no pieces detected (0 nonzero bytes). "
                          "Ensure exactly one piece is on the board.")
                # We can't decode to exact square here yet, but we keep full STATE/F0 for later mapping.

            # Write outputs
            out_jsonl.write(json.dumps(rec) + "\n")
            out_jsonl.flush()
            write_csv_row(cw, rec)

            total += 1
            print(f"Captured {total}: {title} (attempt {i+1}/{repeat})")

    print("\nGuided plan complete.")
    print(f"Saved {total} capture(s) in this run.")


def piece_name(p: str) -> str:
    return {
        "P": "pawn",
        "N": "knight",
        "B": "bishop",
        "R": "rook",
        "Q": "queen",
        "K": "king",
    }.get(p.upper(), p)


# ------------------------- CSV handling -------------------------

CSV_FIELDS = [
    "timestamp",
    "label",
    "fen",
    "meta.mode",
    "meta.label_piece",
    "meta.label_color",
    "meta.label_square",
    "state_payload_hex",
    "f0_payload_hex",
    "f4_payload_hex",
    "b2_payload_hex",
    "f0_bucket_count",
    "f0_total_non7f_bytes",
    "f0_total_energy",
    "occupancy_payload_len",
    "occupancy_nonzero_bytes",
]

def csv_writer(csv_file):
    writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
    writer.writeheader()
    csv_file.flush()
    return writer

def write_csv_row(writer, rec: Dict[str, Any]):
    # Flatten a couple of meta fields for convenience
    flat = {
        "timestamp": rec.get("timestamp", ""),
        "label": rec.get("label", ""),
        "fen": rec.get("fen", ""),
        "meta.mode": (rec.get("meta") or {}).get("mode", ""),
        "meta.label_piece": (rec.get("meta") or {}).get("label_piece", ""),
        "meta.label_color": (rec.get("meta") or {}).get("label_color", ""),
        "meta.label_square": (rec.get("meta") or {}).get("label_square", ""),
        "state_payload_hex": rec.get("state_payload_hex", ""),
        "f0_payload_hex": rec.get("f0_payload_hex", ""),
        "f4_payload_hex": rec.get("f4_payload_hex", ""),
        "b2_payload_hex": rec.get("b2_payload_hex", ""),
        "f0_bucket_count": rec.get("f0_bucket_count", ""),
        "f0_total_non7f_bytes": rec.get("f0_total_non7f_bytes", ""),
        "f0_total_energy": rec.get("f0_total_energy", ""),
        "occupancy_payload_len": rec.get("occupancy_payload_len", ""),
        "occupancy_nonzero_bytes": rec.get("occupancy_nonzero_bytes", ""),
    }
    writer.writerow(flat)


# ------------------------- CLI and main -------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="Capture DGT Centaur F0/F4/96 snapshots with guided labeling.")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--fen", type=str, help="Single FEN to capture (skips guided plan).")
    g.add_argument("--fens", type=str, help="Path to file with one FEN per line (skips guided plan).")
    ap.add_argument("--skip-plan", action="store_true", help="Skip the guided plan and only run --fen/--fens if provided.")
    ap.add_argument("--repeat", type=int, default=1, help="Number of captures per step/FEN (default: 1).")
    ap.add_argument("--out", type=str, default=".", help="Base output directory (default: current dir).")
    ap.add_argument("--label", type=str, default="", help="Optional label to tag each capture (e.g., 'cal_A').")
    ap.add_argument("--skip-confirm", action="store_true", help="Do not prompt Y/n before captures.")
    return ap.parse_args()


def load_fens(args) -> List[str]:
    if args.fen:
        return [args.fen.strip()]
    if args.fens:
        fens = []
        with open(args.fens, "r", encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                fens.append(s)
        if not fens:
            raise SystemExit("No FENs found in the provided file.")
        return fens
    return []


def main():
    args = parse_args()
    outdir = ensure_outdir(args.out)
    jsonl_path = os.path.join(outdir, "captures.jsonl")
    csv_path = os.path.join(outdir, "captures.csv")

    print(f"Output directory: {outdir}")
    print(f"JSONL: {jsonl_path}")
    print(f"CSV:   {csv_path}")

    try:
        board = Board()
    except Exception as e:
        print(f"Failed to initialize Board(): {e}", file=sys.stderr)
        sys.exit(1)

    with open(jsonl_path, "w", encoding="utf-8") as jfh, open(csv_path, "w", newline="", encoding="utf-8") as cfh:
        # CSV writer
        cw = csv_writer(cfh)

        # If user provided FENs explicitly, run those (optionally skipping the guided plan)
        custom_fens = load_fens(args)
        ran_anything = False

        if custom_fens:
            if not args.skip_plan:
                print("\nNOTE: You provided --fen/--fens; the guided plan will RUN FIRST, then your custom FENs.")
            else:
                print("\nRunning ONLY your provided FENs (guided plan skipped).")

        if not args.skip_plan:
            run_guided_plan(board, jfh, cfh, args.label, args.repeat, args.skip_confirm)
            ran_anything = True

        # Now run user-specified FENs, if any
        for fen in custom_fens:
            title = "Custom FEN capture"
            instructions = "Set up the position as shown."
            if prompt_user_setup(board, title, fen, instructions, args.skip_confirm):
                for i in range(args.repeat):
                    rec = capture_once(board, fen, args.label, extra_meta={"mode": "custom_fen"})
                    jfh.write(json.dumps(rec) + "\n")
                    jfh.flush()
                    write_csv_row(cw, rec)
                    print(f"Captured custom FEN ({i+1}/{args.repeat})")
                ran_anything = True
            else:
                print("Skipped custom FEN.")

        if not ran_anything:
            print("\nNo work performed (you skipped the guided plan and provided no FENs).")

    print("\nDone.")
    print(f"- JSONL (full details): {jsonl_path}")
    print(f"- CSV  (summary):       {csv_path}")
    print("Send me the JSONL/CSV and I’ll analyze separability and sketch the first per-piece templates.")


if __name__ == "__main__":
    main()
