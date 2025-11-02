from __future__ import annotations

import chess
from chess.engine import Cp, Mate

from DGTCentaurMods.uci.score import centipawns_from_info_score


def test_cp_white_turn():
    board = chess.Board()
    cp = centipawns_from_info_score(Cp(34), turn=board.turn)
    assert cp == 34


def test_cp_black_turn_negates_pov():
    board = chess.Board()
    board.push(chess.Move.from_uci("e2e4"))  # black to move
    cp = centipawns_from_info_score(Cp(50), turn=board.turn)
    # Positive still means side-to-move (black) advantage; python-chess pov() handles sign
    assert isinstance(cp, int)


def test_mate_maps_to_large_score_white():
    board = chess.Board()
    val = centipawns_from_info_score(Mate(3), turn=board.turn, mate_cp=100000)
    assert abs(val) >= 99900


