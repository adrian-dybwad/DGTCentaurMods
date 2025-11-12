#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centaur F0/F4/96 Data Collector + Interactive Labeling (extended)

NEW:
- Configurable single-piece sweep: --pieces, --colors, --squares, --per-square-repeats
- Plan switches: --no-empty, --no-startpos, --plan-only-single
- Flow: --auto-advance (skip per-capture prompts inside steps)
- Occupancy sanity check (retry option)
- Templates summary written at end (centroids over simple robust features)

Existing:
- Guided plan with empty baseline, startpos, and labeled single-piece captures
- Records STATE(83), F0, F4, 96->b2, timestamps, and metadata
- Saves JSONL (full) and CSV (summary)

Requires:
from DGTCentaurMods.board import board
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.board.logging import log
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
from typing import List, Tuple, Dict, Any, Iterable

# Ensure we import the repo package first (not a system-installed copy)
try:
    REPO_OPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'DGTCentaurMods', 'opt'))
    if REPO_OPT not in sys.path:
        sys.path.insert(0, REPO_OPT)
except Exception:
    pass

from DGTCentaurMods.board import board
from DGTCentaurMods.board.sync_centaur import command
from DGTCentaurMods.board.logging import log


# ------------------------- Low-level helpers -------------------------

def bytes_to_hex(b: bytes) -> str:
    return " ".join(f"{x:02x}" for x in b)

def split_f0_buckets(f0_payload: bytes, sentinel: int = 0x7F) -> List[bytes]:
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
    length = len(b)
    energy = sum(b)
    nnz = sum(1 for x in b if x != 0)
    return length, energy, nnz

def strip_header(msg: bytes, expect_first: int) -> bytes:
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

def parse_list_arg(val: str) -> List[str]:
    """
    Accept comma or space separated values. Return [] if empty/None.
    """
    if not val:
        return []
    # split on comma or whitespace
    parts = [p.strip() for chunk in val.split(",") for p in chunk.split()]
    return [p for p in parts if p]

# ------------------------- Board capture -------------------------

def capture_once(fen: str, label: str, extra_meta: Dict[str, Any]) -> Dict[str, Any]:
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

    # Occupancy quick stats
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
        "f0_bucket_stats": bucket_stats,
        "occupancy_payload_len": occupancy_len,
        "occupancy_nonzero_bytes": occupancy_nonzero,
    }
    return record

# ------------------------- Guided plan -------------------------

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
EMPTY_FEN = "8/8/8/8/8/8/8/8 w - - 0 1"

PIECES = ["P", "N", "B", "R", "Q", "K"]
FILES = "abcdefgh"
RANKS = "12345678"

def valid_square(s: str) -> bool:
    return len(s) == 2 and s[0] in FILES and s[1] in RANKS

def piece_name(p: str) -> str:
    return {"P":"pawn","N":"knight","B":"bishop","R":"rook","Q":"queen","K":"king"}.get(p.upper(), p)

def prompt_user_setup(title: str, fen: str, instructions: str, skip_confirm: bool) -> bool:
    print("\n==================================================")
    print(f"{title}")
    print(f"Target FEN:\n  {fen}")
    print(f"Instructions:\n  {instructions}")
    try:
        board.printChessState()
    except Exception as e:
        log.warning(f"printChessState() failed (continuing): {e}")
    if skip_confirm:
        return True
    return prompt_yes_no("Ready to capture?", default_yes=True)

def plan_single_piece_steps(
    pieces: Iterable[str],
    colors: Iterable[str],
    squares: Iterable[str],
) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for color in colors:
        for p in pieces:
            for sq in squares:
                steps.append({
                    "title": f"Labeled single-piece ({piece_name(p)} {('white' if color=='w' else 'black')} on {sq})",
                    "fen": EMPTY_FEN,
                    "instructions": f"Place exactly ONE {('white' if color=='w' else 'black')} {piece_name(p)} on {sq}. Leave all other squares empty.",
                    "mode": "label_single_piece",
                    "piece": p.upper(),
                    "square": sq.lower(),
                    "color": color.lower()
                })
    return steps

def run_steps(out_jsonl, out_csv, label: str, repeat: int, skip_confirm: bool, auto_advance: bool, steps: List[Dict[str, Any]]):
    cw = csv_writer(out_csv)
    total = 0
    for step in steps:
        title = step["title"]
        fen = step.get("fen", EMPTY_FEN)
        instructions = step.get("instructions", "")
        mode = step["mode"]

        if not prompt_user_setup(title, fen, instructions, skip_confirm):
            print("Skipped.")
            continue

        extra_meta = {"mode": mode}

        # Allow on-the-fly override for labeled single-piece steps
        if mode == "label_single_piece":
            planned_piece = step["piece"]
            planned_square = step["square"]
            planned_color = step["color"]
            print(f"Planned: {piece_name(planned_piece)} on {planned_square} ({'white' if planned_color=='w' else 'black'})")
            if not prompt_yes_no("Use the planned piece/square/color?", default_yes=True):
                piece = input("Enter piece type [P,N,B,R,Q,K]: ").strip().upper() or planned_piece
                if piece not in PIECES:
                    print("Invalid piece; defaulting to planned.")
                    piece = planned_piece
                square = input("Enter square (e.g., e4): ").strip().lower() or planned_square
                if not valid_square(square):
                    print("Invalid square; defaulting to planned.")
                    square = planned_square
                color = (input("Enter color [w/b]: ").strip().lower() or planned_color)
                if color not in ("w","b"):
                    print("Invalid color; defaulting to planned.")
                    color = planned_color
            else:
                piece, square, color = planned_piece, planned_square, planned_color

            extra_meta.update({
                "label_piece": piece,
                "label_color": color,
                "label_square": square
            })
            print(f"→ Recording as: {piece_name(piece)} on {square} ({'white' if color=='w' else 'black'})")

        # Inner repeats per step
        attempt = 0
        while attempt < repeat:
            if not auto_advance and attempt > 0:
                if not prompt_yes_no("Capture another repeat for this step?", default_yes=True):
                    break

            try:
                rec = capture_once(fen, label, extra_meta)
            except Exception as e:
                log.error(f"Capture failed ({title}, attempt {attempt+1}/{repeat}): {e}")
                if not prompt_yes_no("Retry this attempt?", default_yes=True):
                    break
                continue

            # For labeled steps, sanity-check occupancy: we expect exactly 1 nonzero byte
            if mode == "label_single_piece":
                occ_nz = rec.get("occupancy_nonzero_bytes", 0)
                if occ_nz != 1:
                    print(f"WARNING: Occupancy suggests {occ_nz} nonzero byte(s), expected exactly 1.")
                    if prompt_yes_no("Retry this capture?", default_yes=True):
                        continue  # retry without incrementing attempt

            # Persist
            out_jsonl.write(json.dumps(rec) + "\n")
            out_jsonl.flush()
            write_csv_row(cw, rec)

            total += 1
            attempt += 1
            print(f"Captured {total}: {title} (repeat {attempt}/{repeat})")

    print("\nPlan complete.")
    print(f"Saved {total} capture(s) in this run.")

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

# ------------------------- Templates summary -------------------------

def write_templates_summary(outdir: str, jsonl_path: str):
    """
    Pure-Python summary (no pandas).
    Builds per-(piece,color) stats over:
      - f0_total_non7f_bytes
      - f0_total_energy
    Writes templates_summary.json and templates_summary.csv
    """
    PIECES = ["P","N","B","R","Q","K"]
    import math

    def mean(xs):
        xs = [float(x) for x in xs]
        return sum(xs)/len(xs) if xs else float('nan')

    def stdev(xs):
        xs = [float(x) for x in xs]
        n = len(xs)
        if n < 2: return float('nan')
        mu = mean(xs)
        var = sum((x-mu)**2 for x in xs)/(n-1)
        return math.sqrt(var)

    groups = {}  # (piece,color) -> {"non7f":[], "energy":[]}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            meta = rec.get("meta") or {}
            if meta.get("mode") != "label_single_piece":
                continue
            piece = (meta.get("label_piece") or "").upper()
            color = (meta.get("label_color") or "").lower()
            if piece not in PIECES or color not in ("w","b"):
                continue
            non7f = rec.get("f0_total_non7f_bytes")
            energy = rec.get("f0_total_energy")
            if non7f is None or energy is None:
                continue
            groups.setdefault((piece,color), {"non7f":[], "energy":[]})
            groups[(piece,color)]["non7f"].append(non7f)
            groups[(piece,color)]["energy"].append(energy)

    if not groups:
        print("No labeled single-piece rows found; templates summary skipped.")
        return

    # Write CSV
    csv_path = os.path.join(outdir, "templates_summary.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["piece","color","count",
                    "non7f_mean","non7f_std","non7f_min","non7f_max",
                    "energy_mean","energy_std","energy_min","energy_max"])
        for (piece,color), vals in sorted(groups.items()):
            n = len(vals["non7f"])
            non7f_mean = mean(vals["non7f"])
            non7f_std  = stdev(vals["non7f"])
            energy_mean = mean(vals["energy"])
            energy_std  = stdev(vals["energy"])
            w.writerow([
                piece, color, n,
                f"{non7f_mean:.6g}", f"{non7f_std:.6g}", min(vals["non7f"]), max(vals["non7f"]),
                f"{energy_mean:.6g}", f"{energy_std:.6g}", min(vals["energy"]), max(vals["energy"]),
            ])

    # Write JSON
    json_path = os.path.join(outdir, "templates_summary.json")
    comp = {}
    for (piece,color), vals in groups.items():
        key = f"{piece}{color}"
        comp[key] = {
            "count": len(vals["non7f"]),
            "non7f_mean": mean(vals["non7f"]),
            "non7f_std": stdev(vals["non7f"]),
            "energy_mean": mean(vals["energy"]),
            "energy_std": stdev(vals["energy"]),
            "non7f_min": min(vals["non7f"]),
            "non7f_max": max(vals["non7f"]),
            "energy_min": min(vals["energy"]),
            "energy_max": max(vals["energy"]),
        }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(comp, fh, indent=2)

    print(f"Templates summary written:\n- {csv_path}\n- {json_path}")

# ------------------------- CLI and main -------------------------

def parse_args():
    ap = argparse.ArgumentParser(description="Capture DGT Centaur F0/F4/96 snapshots with guided labeling (extended).")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--fen", type=str, help="Single FEN to capture (skips guided plan).")
    g.add_argument("--fens", type=str, help="Path to file with one FEN per line (skips guided plan).")

    # Plan composition
    ap.add_argument("--no-empty", action="store_true", help="Skip empty-board baseline step.")
    ap.add_argument("--no-startpos", action="store_true", help="Skip full starting position step.")
    ap.add_argument("--plan-only-single", action="store_true", help="Run only the single-piece plan.")

    # Single-piece sweep controls
    ap.add_argument("--pieces", type=str, default="P,N,B,R,Q,K",
                    help="Pieces to capture (comma/space separated). Default: P,N,B,R,Q,K")
    ap.add_argument("--colors", type=str, default="w",
                    help="Colors to capture: w,b (comma/space separated). Default: w")
    ap.add_argument("--squares", type=str, default="a1,c1,e1,a2,d2,h2",
                    help="Squares to use for single-piece captures (comma/space separated).")
    ap.add_argument("--per-square-repeats", type=int, default=1,
                    help="Number of captures per (piece,color,square). Default: 1")

    # Flow
    ap.add_argument("--repeat", type=int, default=1, help="Number of captures per generic step/FEN (legacy).")
    ap.add_argument("--auto-advance", action="store_true", help="Skip prompts between repeats inside a step.")
    ap.add_argument("--skip-plan", action="store_true", help="Skip the guided plan and only run --fen/--fens if provided.")
    ap.add_argument("--skip-confirm", action="store_true", help="Do not prompt Y/n before steps.")

    # Output & labeling
    ap.add_argument("--out", type=str, default=".", help="Base output directory (default: current dir).")
    ap.add_argument("--label", type=str, default="", help="Optional label to tag each capture (e.g., 'cal_A').")
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

    with open(jsonl_path, "w", encoding="utf-8") as jfh, open(csv_path, "w", newline="", encoding="utf-8") as cfh:
        cw = csv_writer(cfh)

        custom_fens = load_fens(args)
        ran_anything = False

        if custom_fens:
            if not args.skip_plan:
                print("\nNOTE: You provided --fen/--fens; the guided plan will RUN FIRST, then your custom FENs.")
            else:
                print("\nRunning ONLY your provided FENs (guided plan skipped).")

        # ----- Guided plan -----
        if not args.skip_plan:
            steps: List[Dict[str, Any]] = []

            # Baselines unless suppressed or plan-only-single
            if not args.plan_only_single and not args.no_empty:
                steps.append({
                    "title": "Empty-board baseline",
                    "fen": EMPTY_FEN,
                    "instructions": "Remove all pieces from the board.",
                    "mode": "guided_fen",
                })
            if not args.plan_only_single and not args.no_startpos:
                steps.append({
                    "title": "Full starting position",
                    "fen": START_FEN,
                    "instructions": "Set up the full chess starting position: white on your side (ranks 1-2).",
                    "mode": "guided_fen",
                })

            # Single-piece sweep
            sweep_pieces = [p.upper() for p in parse_list_arg(args.pieces) if p.upper() in PIECES]
            sweep_colors = [c.lower() for c in parse_list_arg(args.colors) if c.lower() in ("w","b")]
            sweep_squares = [s.lower() for s in parse_list_arg(args.squares) if valid_square(s.lower())]

            if not sweep_pieces:
                sweep_pieces = PIECES[:]  # default fallback
            if not sweep_colors:
                sweep_colors = ["w"]
            if not sweep_squares:
                sweep_squares = ["a1","c1","e1","a2","d2","h2"]

            single_steps = plan_single_piece_steps(sweep_pieces, sweep_colors, sweep_squares)
            # We encode the per-square repeats on the step itself so run_steps can use it via 'repeat'
            # but we'll pass args.per_square_repeats as 'repeat' when executing the single-steps.
            # Baselines use args.repeat as before.

            # Run baseline steps with args.repeat
            baseline_steps = [s for s in steps if s["mode"] == "guided_fen"]
            if baseline_steps:
                run_steps(jfh, cfh, args.label, repeat=args.repeat, skip_confirm=args.skip_confirm,
                          auto_advance=args.auto_advance, steps=baseline_steps)
                ran_anything = True

            # Run single-piece steps with per-square repeats
            if single_steps:
                run_steps(jfh, cfh, args.label, repeat=args.per_square_repeats, skip_confirm=args.skip_confirm,
                          auto_advance=args.auto_advance, steps=single_steps)
                ran_anything = True

        # ----- Custom FENs -----
        for fen in custom_fens:
            title = "Custom FEN capture"
            instructions = "Set up the position as shown."
            if prompt_user_setup(title, fen, instructions, args.skip_confirm):
                # Use args.repeat for custom FENs
                for i in range(args.repeat):
                    rec = capture_once(fen, args.label, extra_meta={"mode": "custom_fen"})
                    jfh.write(json.dumps(rec) + "\n")
                    jfh.flush()
                    write_csv_row(cw, rec)
                    print(f"Captured custom FEN ({i+1}/{args.repeat})")
                ran_anything = True
            else:
                print("Skipped custom FEN.")

        if not ran_anything:
            print("\nNo work performed (you skipped the guided plan and provided no FENs).")

    # Build quick templates summary (from JSONL) for immediate iteration
    write_templates_summary(outdir, jsonl_path)

    print("\nDone.")
    print(f"- JSONL (full details): {jsonl_path}")
    print(f"- CSV  (summary):       {csv_path}")
    print(f"- Templates summary:    {os.path.join(outdir, 'templates_summary.{json,csv}')}")
    print("Send me the JSONL/CSV and templates summary; I’ll iterate on per-piece templates next.")

if __name__ == "__main__":
    main()
