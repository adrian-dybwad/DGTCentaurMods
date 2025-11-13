#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
draw_centaur_board.py

- Shows reliable occupancy from 83 / board.getChessState()
- Parses F0 payload as:
    payload[0] = meta (ignored for now)
    payload[1:129] = 128 bytes of real data -> 64 big-endian uint16 (a8..h1)
- Flips F0 to chess order (a1..h8), same as 83
- Can record per-piece templates (delta vs empty baseline) into a JSON file
- Uses templates to overlay letters (P,N,B,R,Q,K) on occupied squares

Usage examples
--------------

# Just occupancy
python draw_centaur_board.py

# Occupancy + per-square F0 table
python draw_centaur_board.py --show-f0

# Record templates (baseline + pieces)
python draw_centaur_board.py --record-templates \
  --f0-templates f0_templates.json \
  --avg-f0 3 --baseline-repeats 5 --piece-repeats 2 \
  --squares-P "a2 b2 d2 e2 h2" \
  --squares-N "b1 g1" \
  --squares-B "c1 f1" \
  --squares-R "a1 h1" \
  --squares-Q "d1" \
  --squares-K "e1"

# Draw with letters using templates
python draw_centaur_board.py --f0-templates f0_templates.json --avg-f0 3
"""

import argparse
import json
import os
import sys
import time
import statistics
from typing import Dict, List, Optional

# Prefer repo's opt path
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
PIECES = ["P", "N", "B", "R", "Q", "K"]


# -------------------- generic helpers --------------------

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


def squares_visual_order(orientation: str) -> List[str]:
    order: List[str] = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    for r in ranks:
        for f in FILES:
            order.append(f"{f}{r}")
    return order


def format_board(assignments: Dict[str, str], orientation: str) -> str:
    lines: List[str] = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    lines.append("    " + " ".join(FILES))
    lines.append("    " + "-" * (len(FILES) * 2 - 1))
    for r in ranks:
        row = [assignments.get(f"{f}{r}", ".") for f in FILES]
        lines.append(f"{r} | " + " ".join(row))
    return "\n".join(lines)


def square_to_index(sq: str) -> int:
    sq = sq.strip().lower()
    f = FILES.index(sq[0])
    r = int(sq[1]) - 1
    return r * 8 + f  # chess order index (a1..h8)


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

def _get_chess_state_from_module() -> Optional[List[int]]:
    """Use board.getChessState() if available: chess order a1..h8."""
    try:
        st = list(board.getChessState())
        return [1 if int(x) != 0 else 0 for x in st]
    except Exception:
        return None


def _get_chess_state_from_raw() -> Optional[List[int]]:
    """Fallback: use board.getBoardState() raw (a8..h1), flip vertically."""
    try:
        raw = list(board.getBoardState())
    except Exception:
        return None
    if len(raw) != 64:
        return None
    chess = [0] * 64
    for i in range(64):
        raw_row = i // 8
        raw_col = i % 8
        chess_row = 7 - raw_row
        chess_col = raw_col
        chess_idx = chess_row * 8 + chess_col
        chess[chess_idx] = 1 if int(raw[i]) != 0 else 0
    return chess


def occupancy_chess() -> List[int]:
    st = _get_chess_state_from_module()
    if st is None:
        st = _get_chess_state_from_raw()
    if st is None or len(st) != 64:
        try:
            board.printChessState()
        except Exception:
            pass
        return [0] * 64
    return st


# -------------------- F0 parsing: meta + 64×uint16 raw a8..h1 --------------------

def get_f0_payload() -> bytes:
    """
    F0 payload only; sendCommand already stripped headers/CS.
    Observed layout:
      payload[0]   = meta (often mirrors 0x7F we send, or a max marker)
      payload[1:129] = 128 bytes of real F0 data -> 64 × uint16, big-endian, a8..h1
      payload[129:]  = extra / unknown (ignored)
    """
    try:
        return board.sendCommand(command.DGT_BUS_SEND_SNAPSHOT_F0)
    except Exception as e:
        log.error(f"F0 read failed: {e}")
        return b""


def parse_f0_u16_raw_a8h1(payload: bytes) -> Optional[List[int]]:
    """
    Interpret bytes 1..128 of the payload as the 64 big-endian uint16 values.
    payload[0] is metadata and must be skipped.
    """
    if len(payload) < 129:  # 1 meta + 128 data
        log.warning(f"F0 payload too short ({len(payload)} bytes); need >=129.")
        return None

    meta = payload[0]
    log.debug(f"F0 meta byte: 0x{meta:02x}")

    data = payload[1:129]  # 128 bytes of real data

    vals: List[int] = []
    for i in range(0, 128, 2):
        hi = data[i]
        lo = data[i + 1]
        vals.append((hi << 8) | lo)

    if len(vals) != 64:
        log.warning(f"F0 parse produced {len(vals)} values (expected 64).")
        return None

    return vals


def f0_raw_to_chess(u16_raw: List[int]) -> List[int]:
    """
    Flip raw a8..h1 → chess a1..h8 (same vertical flip as 83).
    """
    chess = [0] * 64
    for i in range(64):
        raw_row, raw_col = divmod(i, 8)
        chess_row = 7 - raw_row
        chess_col = raw_col
        chess[chess_row * 8 + chess_col] = u16_raw[i]
    return chess


def f0_seq_chess(avg: int = 1) -> Optional[List[int]]:
    """
    Read F0 and return per-square values in chess order, averaging 'avg' samples.
    """
    vals_acc: List[List[int]] = []
    for _ in range(max(1, avg)):
        payload = get_f0_payload()
        u16_raw = parse_f0_u16_raw_a8h1(payload)
        if u16_raw is None:
            return None
        vals_acc.append(u16_raw)
        time.sleep(0.03)

    if len(vals_acc) == 1:
        return f0_raw_to_chess(vals_acc[0])

    mean_raw = [
        int(round(sum(v[i] for v in vals_acc) / len(vals_acc)))
        for i in range(64)
    ]
    return f0_raw_to_chess(mean_raw)


def format_f0_table(f0_chess: List[int], orientation: str, width: int = 5) -> str:
    lines: List[str] = []
    ranks = list(reversed(RANKS)) if orientation == "white-bottom" else list(RANKS)
    header = "    " + " ".join(f"{f:>{width}}" for f in FILES)
    lines.append(header)
    lines.append("    " + "-" * (len(FILES) * (width + 1) - 1))
    for r in ranks:
        row_vals: List[str] = []
        for f in FILES:
            idx = (int(r) - 1) * 8 + FILES.index(f)
            row_vals.append(f"{f0_chess[idx]:>{width}}")
        lines.append(f"{r} | " + " ".join(row_vals))
    return "\n".join(lines)


# -------------------- Classification using templates --------------------

def classify_delta(delta: float, tmpl: Dict[str, Dict[str, float]]) -> str:
    """
    Given a delta for one occupied square and per-piece {mean_delta, std_delta},
    pick the nearest (z-scored) piece.
    """
    best_piece = "?"
    best_score = float("inf")
    for p in PIECES:
        stats = tmpl.get(p) or {}
        mu = stats.get("mean_delta")
        sd = stats.get("std_delta", 0.0)
        if mu is None:
            continue
        if sd and sd > 1e-9:
            score = ((delta - mu) / sd) ** 2
        else:
            score = abs(delta - mu)
        if score < best_score:
            best_score = score
            best_piece = p
    return best_piece


def overlay_letters_with_templates(assign: Dict[str, str],
                                   occ: List[int],
                                   orientation: str,
                                   templates_path: str,
                                   f0_chess: Optional[List[int]]) -> None:
    """
    Overlay letters on occupied squares using F0 delta vs baseline and
    per-piece templates.
    """
    tmpl = load_json(templates_path)
    baseline = tmpl.get("baseline") or []
    pieces = tmpl.get("pieces") or {}
    if len(baseline) != 64 or not pieces or f0_chess is None:
        return

    vis = squares_visual_order(orientation)
    for sq in vis:
        f, r = sq[0], int(sq[1])
        idx = (r - 1) * 8 + FILES.index(f)
        if occ[idx] == 1:
            delta = max(float(f0_chess[idx]) - float(baseline[idx]), 0.0)
            assign[sq] = classify_delta(delta, pieces)


# -------------------- Template recorder --------------------

def record_baseline(avg: int, repeats: int) -> List[float]:
    print(f"\nBaseline: ensure EMPTY board. Capturing {repeats}× (avg each={avg})...")
    samples: List[List[int]] = []
    for i in range(repeats):
        f0_chess = f0_seq_chess(avg=avg)
        if f0_chess is None:
            print("  - F0 read failed; retrying...")
            time.sleep(0.1)
            continue
        samples.append(f0_chess)
        time.sleep(0.05)
    if not samples:
        raise RuntimeError("No F0 samples collected for baseline.")
    mean = [sum(v[i] for v in samples) / len(samples) for i in range(64)]
    print("Baseline complete.")
    return mean


def ensure_single_on_square(sq: str) -> None:
    occ = occupancy_chess()
    ones = [i for i, v in enumerate(occ) if v == 1]
    idx = square_to_index(sq)
    if len(ones) != 1 or ones[0] != idx:
        print(f"WARNING: expected exactly one piece on {sq}; got {len(ones)} on {ones}. Continuing...")


def record_piece(piece: str,
                 squares: List[str],
                 baseline: List[float],
                 avg: int,
                 repeats: int) -> List[float]:
    deltas: List[float] = []
    print(f"\nRecording {piece}: {len(squares)} square(s), repeats={repeats}, avg={avg}")
    for sq in squares:
        sq = sq.strip().lower()
        if len(sq) != 2 or sq[0] not in FILES or sq[1] not in RANKS:
            print(f"  - skip invalid square '{sq}'")
            continue

        input(f"Place ONE {piece} on {sq}, then press Enter...")
        ensure_single_on_square(sq)

        per: List[float] = []
        for _ in range(repeats):
            f0_chess = f0_seq_chess(avg=avg)
            if f0_chess is None:
                print("    F0 read failed; retrying...")
                time.sleep(0.1)
                continue
            idx = square_to_index(sq)
            per.append(max(float(f0_chess[idx]) - float(baseline[idx]), 0.0))
            time.sleep(0.05)

        if per:
            mu = sum(per) / len(per)
            deltas.append(mu)
            print(f"  {piece}@{sq}: mean Δ={mu:.1f} (n={len(per)})")
        else:
            print(f"  {piece}@{sq}: no usable samples")
        input("Remove the piece, then press Enter...")

    return deltas


def run_template_recorder(args) -> None:
    print("\n=== Template Recorder (F0 delta vs empty) ===")
    input("Make sure the board is EMPTY, then press Enter to start baseline...")
    baseline = record_baseline(avg=args.avg_f0, repeats=args.baseline_repeats)

    def parse_sq_list(s: str, default: str) -> List[str]:
        toks = (s or default).replace(",", " ").split()
        out: List[str] = []
        for t in toks:
            t = t.strip().lower()
            if len(t) == 2 and t[0] in FILES and t[1] in RANKS:
                out.append(t)
        return out

    squares_by_piece: Dict[str, List[str]] = {
        "P": parse_sq_list(args.squares_P, "a2 b2 d2 e2 h2"),
        "N": parse_sq_list(args.squares_N, "b1 g1"),
        "B": parse_sq_list(args.squares_B, "c1 f1"),
        "R": parse_sq_list(args.squares_R, "a1 h1"),
        "Q": parse_sq_list(args.squares_Q, "d1"),
        "K": parse_sq_list(args.squares_K, "e1"),
    }

    stats: Dict[str, Dict[str, float]] = {}
    for p in PIECES:
        deltas = record_piece(p, squares_by_piece[p], baseline, avg=args.avg_f0, repeats=args.piece_repeats)
        if deltas:
            mu = sum(deltas) / len(deltas)
            sd = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
        else:
            mu = 0.0
            sd = 0.0
        stats[p] = {"mean_delta": mu, "std_delta": sd, "n": len(deltas)}
        print(f"→ {p}: mean Δ={mu:.1f}, std Δ={sd:.1f}, n={len(deltas)}")

    out = {
        "format": "centaur_f0_per_square_templates_v1",
        "baseline": baseline,  # 64 floats, chess order a1..h8
        "pieces": stats
    }
    save_json(args.f0_templates, out)
    print(f"\nSaved templates → {args.f0_templates}")
    print(f"You can now draw with letters:\n  python {os.path.basename(__file__)} --f0-templates {args.f0_templates}")


# -------------------- draw loop --------------------

def draw_once(orientation: str,
              show_f0: bool,
              f0_templates: str,
              avg_f0: int) -> str:
    # 83 occupancy
    occ = occupancy_chess()
    vis = squares_visual_order(orientation)
    assign: Dict[str, str] = {}
    for sq in vis:
        f, r = sq[0], int(sq[1])
        idx = (r - 1) * 8 + FILES.index(f)
        assign[sq] = "?" if occ[idx] else "."

    # F0 (optional, for letters and/or table)
    f0_chess: Optional[List[int]] = None
    try:
        f0_chess = f0_seq_chess(avg=avg_f0)
    except Exception as e:
        log.error(f"F0 read error: {e}")
        f0_chess = None

    # Overlay letters if templates available and F0 is valid
    if f0_templates and f0_chess is not None:
        overlay_letters_with_templates(assign, occ, orientation, f0_templates, f0_chess)

    # Optional F0 table
    f0_table = ""
    if show_f0 and f0_chess is not None:
        f0_table = "\n\nF0 per-square (uint16-ish):\n" + format_f0_table(f0_chess, orientation)

    try:
        board.printChessState()
    except Exception:
        pass

    return "Detected board:\n" + format_board(assign, orientation) + f0_table


# -------------------- CLI --------------------

def parse_args():
    ap = argparse.ArgumentParser(description="83 occupancy + F0(64×uint16) templates & live letters.")
    ap.add_argument("--orientation", choices=["white-bottom", "black-bottom"], default="white-bottom")
    ap.add_argument("--show-f0", action="store_true", help="Print per-square F0 values table.")
    ap.add_argument("--f0-templates", type=str, default="", help="Templates JSON for live letters.")
    ap.add_argument("--record-templates", action="store_true", help="Run the guided template recorder.")
    ap.add_argument("--avg-f0", type=int, default=3, help="Average this many F0 reads each time F0 is used.")
    ap.add_argument("--baseline-repeats", type=int, default=5, help="Baseline captures (EMPTY board).")
    ap.add_argument("--piece-repeats", type=int, default=2, help="Captures per square per piece.")
    ap.add_argument("--squares-P", type=str, default="", help="Pawn squares (default: a2 b2 d2 e2 h2)")
    ap.add_argument("--squares-N", type=str, default="", help="Knight squares (default: b1 g1)")
    ap.add_argument("--squares-B", type=str, default="", help="Bishop squares (default: c1 f1)")
    ap.add_argument("--squares-R", type=str, default="", help="Rook squares (default: a1 h1)")
    ap.add_argument("--squares-Q", type=str, default="", help="Queen squares (default: d1)")
    ap.add_argument("--squares-K", type=str, default="", help="King squares (default: e1)")
    return ap.parse_args()


def main():
    args = parse_args()

    if args.record_templates:
        run_template_recorder(args)
        # fall through so you can immediately see letters afterwards

    while True:
        try:
            out = draw_once(args.orientation, args.show_f0, args.f0_templates, args.avg_f0)
            print("\n" + out)
        except Exception as e:
            print(f"\nERROR: {e}", file=sys.stderr)

        if not prompt_yes_no("\nRedraw after moving pieces?", default_yes=True):
            break


if __name__ == "__main__":
    main()
