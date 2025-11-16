from __future__ import annotations

import argparse

from DGTCentaurMods.uci.cli import _parse_args, _resolve_cli


def test_legacy_positionals_map_to_flags():
    ns = _parse_args(["uci.py", "white", "stockfish", "Default"])  # legacy
    ns = _resolve_cli(ns)
    assert ns.color == "white"
    assert ns.engine == "stockfish"
    assert ns.profile == "Default"


def test_flags_take_precedence():
    ns = _parse_args(["uci.py", "--color", "black", "--engine", "sf", "white", "stockfish"])  # flags + legacy
    ns = _resolve_cli(ns)
    assert ns.color == "black"
    assert ns.engine == "sf"


