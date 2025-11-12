#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centaur ASCII board using reliable 83 occupancy + F0(64x uint16) per-square values.
Includes a guided template recorder (delta vs empty) and live overlay classification.

Modes
-----
1) Draw (default):
   - Renders occupancy ('?'=occupied, '.'=empty).
   - If --f0-templates is provided (JSON from the recorder), overlays letters P/N/B/R/Q/K.

2) Record templates:
   - Use --record-templates to run a guided wizard:
     * Captures EMPTY baseline (mean of --baseline-repeats)
     * For each piece (P,N,B,R,Q,K), prompts you through squares ( --squares-P / --squares-N / ... )
       and recordings per square ( --piece-repeats ).
     * For each placement, computes delta = max(F0[sq] - baseline[sq], 0) and stores per-piece deltas.
     * At the end, saves JSON with:
         - baseline (64-length baseline array, chess order)
         - per-piece mean_delta and std_delta (global, not per-square)

Usage
-----
# Just occupancy
python draw_centaur_board.py

# Occupancy + F0 values table
python draw_centaur_board.py --show-f0

# Guided template recording (baseline + pieces)
python draw_centaur_board.py --record-templates \
  --f0-templates f0_piece_templates.json \
  --baseline-repeats 5 \
  --piece-repeats 2 \
  --squares-P "a2,b2,d2,e2,h2" \
  --squares-N "b1,g1" \
  --squares-B "c1,f1" \
  --squares-R "a1,h1" \
  --squares-Q "d1" \
  --squares-K "e1"

# Live drawing with letters using recorded templates
python draw_centaur_board.py --f0-templates f0_piece_templates.json
"""

import argparse, json, os, sys, statistics, time
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
PIECES = ["P","N","B","R","Q","K"]

# -------------------- helpers --------------------

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
    # Centaur messages commonly have a 5-byte header when captured via sendCommand.
    if len(msg) >= 5 and msg[0] == expect_first:
        return msg[5:]
    return msg

def square_to_index(sq: str) -> int:
    sq = sq.lower().strip()
    f = FILES.index(sq[0]); r = int(sq[1]) - 1
    return r*8 + f  # chess order index (a1..h8)

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

# -------------------- 83 occupancy (reliable) --------------------

def get_chess_state_from_module() -> Optional[List[int]]:
    try:
        st = list(board.getChessState())  # chess order a1..h8
        return [1 if int(x)!=0 else 0 for x in st]
    except Exception:
        return None

def get_chess_state_from_raw() -> Optional[List[int]]:
    try:
        raw = list(board.getBoardState())  # raw order a8..h1
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

# -------------------- F0 parsing: 64x uint16 (big-endian), raw a8..h1 --------------------

def get_f0_u16_raw_a8h1() -> Optional[List[int]]:
    try:
        resp_f0 = board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    except Exception as e:
        log.error(f"F0 read failed: {e}")
        return None
    payload = strip_header(resp_f0, 0xF0)

    # Expect at least 128 bytes for 64 big-endian uint16 values
    if len(payload) < 128:
        log.warning(f"F0 payload too short ({len(payload)} bytes).")
        return None
    data = payload[:128]

    vals = []
    for i in range(0, 128, 2):
        hi, lo = data[i], data[i+1]
        vals.append(hi*256 + lo)
    if len(vals) != 64:
        return None
    return vals  # raw order (a8..h1)

def f0_to_chess_order(u16_raw: List[int]) -> List[int]:
    chess = [0]*64
    for i in range(64):
        raw_row = i // 8
        raw_col = i % 8
        chess_row = 7 - raw_row
        chess_col = raw_col
        chess_idx = chess_row*8 + chess_col
        chess[chess_idx] = u16_raw[i]
    return chess  # chess order (a1..h8)

def format_f0_table(f0_chess: List[int], orientation: str, width: int = 5) -> str:
    lines = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    header = "    " + " ".join([f"{f:>{width}}" for f in FILES])
    lines.append(header)
    lines.append("    " + "-" * (len(FILES)*(width+1)-1))
    for r in ranks:
        row_vals = []
        for f in FILES:
            idx = (int(r)-1)*8 + FILES.index(f)
            row_vals.append(f"{f0_chess[idx]:>{width}}")
        lines.append(f"{r} | " + " ".join(row_vals))
    return "\n".join(lines)

# -------------------- Live classification using recorded templates --------------------

def classify_delta(delta: float, tmpl: Dict[str, Dict[str, float]]) -> str:
    """
    Given a delta value for a single occupied square and per-piece {mean_delta, std_delta},
    pick argmin z-score distance. If std=0, fall back to absolute difference.
    """
    best_piece, best_score = "?", float("inf")
    for p in PIECES:
        stats = tmpl.get(p) or {}
        mu = stats.get("mean_delta"); sd = stats.get("std_delta", 0.0)
        if mu is None:
            continue
        if sd and sd > 1e-9:
            score = ((delta - mu)/sd)**2
        else:
            score = abs(delta - mu)
        if score < best_score:
            best_score, best_piece = score, p
    return best_piece

def overlay_letters_with_templates(assign: Dict[str,str],
                                   occ: List[int],
                                   orientation: str,
                                   templates_path: str) -> None:
    """
    If template JSON exists, compute current deltas vs baseline for occupied squares
    and overlay letters using nearest (z-scored) mean.
    """
    tmpl = load_json(templates_path)
    baseline = tmpl.get("baseline") or []
    pieces = tmpl.get("pieces") or {}
    if len(baseline) != 64 or not pieces:
        return

    u16_raw = get_f0_u16_raw_a8h1()
    if not u16_raw:
        return
    f0 = f0_to_chess_order(u16_raw)

    # For each displayed square, if occupied, compute delta vs baseline and classify
    vis = squares_visual_order(orientation)
    for sq in vis:
        f, r = sq[0], int(sq[1])
        idx = (r - 1)*8 + FILES.index(f)
        if occ[idx] == 1:
            delta = max(float(f0[idx]) - float(baseline[idx]), 0.0)
            assign[sq] = classify_delta(delta, pieces)

# -------------------- Template recorder --------------------

def capture_empty_baseline(repeats: int, pause: float = 0.2) -> List[float]:
    """Average several F0 captures on an EMPTY board; return 64-length baseline in chess order."""
    print(f"\nBaseline capture: Ensure the board is EMPTY. Capturing {repeats} samples...")
    vals: List[List[int]] = []
    for i in range(repeats):
        u16_raw = get_f0_u16_raw_a8h1()
        if not u16_raw:
            print("  - F0 read failed; retrying...")
            time.sleep(pause)
            continue
        vals.append(f0_to_chess_order(u16_raw))
        time.sleep(pause)
    if not vals:
        raise RuntimeError("No F0 samples collected for baseline.")
    # element-wise mean
    mean = [ sum(v[i] for v in vals)/len(vals) for i in range(64) ]
    print("Baseline complete.")
    return mean

def ensure_single_on_square(target_sq: str) -> None:
    """Check 83 occupancy shows exactly one piece and it is at target_sq; warn otherwise."""
    occ = get_occupancy_chess_order()
    ones = [i for i,v in enumerate(occ) if v==1]
    idx = square_to_index(target_sq)
    if len(ones) != 1 or (len(ones)==1 and ones[0] != idx):
        print("WARNING: Expected exactly one occupied square at", target_sq,
              f"but got {len(ones)} occupied at indices {ones}. Continuing anyway...")

def record_piece_deltas(piece: str, squares: List[str], repeats: int,
                        baseline: List[float], pause: float = 0.15) -> List[float]:
    """
    For each square: prompt to place ONE piece, capture repeats, compute per-capture delta at that square,
    then average across repeats; return list of deltas across all squares for this piece.
    """
    deltas: List[float] = []
    print(f"\nRecording {piece}: {len(squares)} squares, {repeats} repeats each.")
    for sq in squares:
        sq = sq.strip().lower()
        if len(sq)!=2 or sq[0] not in FILES or sq[1] not in RANKS:
            print(f"  - Skip invalid square '{sq}'")
            continue

        input(f"\nPlace ONE {piece} on {sq}, then press Enter...")
        ensure_single_on_square(sq)

        per_sq_vals: List[float] = []
        for i in range(repeats):
            u16_raw = get_f0_u16_raw_a8h1()
            if not u16_raw:
                print("    F0 read failed; retrying...")
                time.sleep(pause); continue
            f0 = f0_to_chess_order(u16_raw)
            idx = square_to_index(sq)
            delta = max(float(f0[idx]) - float(baseline[idx]), 0.0)
            per_sq_vals.append(delta)
            time.sleep(pause)

        if per_sq_vals:
            mean_delta = sum(per_sq_vals)/len(per_sq_vals)
            deltas.append(mean_delta)
            print(f"  {piece} at {sq}: mean Δ={mean_delta:.1f} (n={len(per_sq_vals)})")
        else:
            print(f"  {piece} at {sq}: no usable samples")

        input("Remove the piece, then press Enter...")

    return deltas

def compute_stats(values: List[float]) -> Tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    mu = sum(values)/len(values)
    if len(values) > 1:
        try:
            sd = statistics.pstdev(values)  # population stdev
        except Exception:
            sd = 0.0
    else:
        sd = 0.0
    return (mu, sd)

def run_template_recorder(args) -> None:
    """
    Wizard:
      1) Capture baseline (mean of --baseline-repeats)
      2) For each piece, iterate squares and collect mean Δ per square
      3) Summarize per piece: mean_delta, std_delta
      4) Save JSON: { baseline: [...64...], pieces: {P:{mean_delta, std_delta}, ...} }
    """
    print("\n=== Template Recorder (F0 delta vs empty) ===")
    input("Ensure the board is EMPTY, then press Enter to start baseline...")
    baseline = capture_empty_baseline(args.baseline_repeats)

    # Parse squares per piece
    def parse_sq_list(s: str, default: str) -> List[str]:
        raw = (s or default).replace(",", " ").split()
        out = []
        for tok in raw:
            tok = tok.strip().lower()
            if len(tok)==2 and tok[0] in FILES and tok[1] in RANKS:
                out.append(tok)
        return out

    squares_by_piece = {
        "P": parse_sq_list(args.squares_P, "a2 b2 d2 e2 h2"),
        "N": parse_sq_list(args.squares_N, "b1 g1"),
        "B": parse_sq_list(args.squares_B, "c1 f1"),
        "R": parse_sq_list(args.squares_R, "a1 h1"),
        "Q": parse_sq_list(args.squares_Q, "d1"),
        "K": parse_sq_list(args.squares_K, "e1"),
    }

    pieces_stats: Dict[str, Dict[str, float]] = {}
    for p in PIECES:
        deltas = record_piece_deltas(p, squares_by_piece[p], args.piece_repeats, baseline)
        mu, sd = compute_stats(deltas)
        pieces_stats[p] = {"mean_delta": mu, "std_delta": sd, "n": len(deltas)}
        print(f"→ {p}: mean Δ={mu:.1f}, std Δ={sd:.1f}, n={len(deltas)}")

    out = {
        "format": "centaur_f0_per_square_templates_v1",
        "baseline": baseline,  # 64 vals in chess order a1..h8
        "pieces": pieces_stats
    }
    save_json(args.f0_templates, out)
    print(f"\nSaved templates to {args.f0_templates}")
    print("You can now draw with letters:")
    print(f"  python {os.path.basename(__file__)} --f0-templates {args.f0_templates}")

# -------------------- draw loop --------------------

def draw_once(orientation: str, show_f0: bool, f0_templates: str) -> str:
    # 83 occupancy
    occ = get_occupancy_chess_order()  # chess order a1..h8

    # Assignments
    vis = squares_visual_order(orientation)
    assign: Dict[str,str] = {}
    for sq in vis:
        f, r = sq[0], int(sq[1])
        idx = (r - 1)*8 + FILES.index(f)
        assign[sq] = "?" if occ[idx] else "."

    # Overlay letters if templates provided
    if f0_templates:
        overlay_letters_with_templates(assign, occ, orientation, f0_templates)

    # Optional F0 table
    f0_table = ""
    if show_f0:
        u16_raw = get_f0_u16_raw_a8h1()
        if u16_raw:
            f0_chess = f0_to_chess_order(u16_raw)
            f0_table = "\n\nF0 per-square (uint16):\n" + format_f0_table(f0_chess, orientation)
        else:
            f0_table = "\n\nF0 per-square (uint16): [unavailable]"

    try:
        board.printChessState()
    except Exception:
        pass

    return "Detected board:\n" + format_board(assign, orientation) + f0_table

# -------------------- CLI --------------------

def parse_args():
    ap = argparse.ArgumentParser(description="ASCII board via 83 + F0(64x uint16); recorder + live classification.")
    ap.add_argument("--orientation", choices=["white-bottom","black-bottom"], default="white-bottom")
    ap.add_argument("--show-f0", action="store_true", help="Print the per-square F0 uint16 values table.")
    ap.add_argument("--f0-templates", type=str, default="", help="Path to f0_piece_templates.json for live letters.")
    ap.add_argument("--record-templates", action="store_true", help="Run the guided template recorder.")

    # Recorder options
    ap.add_argument("--baseline-repeats", type=int, default=5, help="Empty baseline F0 captures to average.")
    ap.add_argument("--piece-repeats", type=int, default=2, help="Captures per square when recording pieces.")

    ap.add_argument("--squares-P", type=str, default="", help="Squares for PAWN recording (default: a2 b2 d2 e2 h2)")
    ap.add_argument("--squares-N", type=str, default="", help="KNIGHT squares (default: b1 g1)")
    ap.add_argument("--squares-B", type=str, default="", help="BISHOP squares (default: c1 f1)")
    ap.add_argument("--squares-R", type=str, default="", help="ROOK squares (default: a1 h1)")
    ap.add_argument("--squares-Q", type=str, default="", help="QUEEN squares (default: d1)")
    ap.add_argument("--squares-K", type=str, default="", help="KING squares (default: e1)")
    return ap.parse_args()

def main():
    args = parse_args()

    if args.record_templates:
        run_template_recorder(args)
        # fall through to draw so you can immediately see letters after recording

    while True:
        try:
            out = draw_once(args.orientation, args.show_f0, args.f0_templates)
            print("\n" + out)
        except Exception as e:
            print(f"\nERROR: {e}", file=sys.stderr)

        if not prompt_yes_no("\nRedraw after moving pieces?", default_yes=True):
            break

if __name__ == "__main__":
    main()
