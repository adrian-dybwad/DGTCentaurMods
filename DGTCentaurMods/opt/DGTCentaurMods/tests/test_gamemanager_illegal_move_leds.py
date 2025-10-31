from __future__ import annotations

from unittest.mock import MagicMock

import chess


def _setup_common(monkeypatch):
    # Import here to ensure module path resolution inside test
    from DGTCentaurMods.game import gamemanager

    # Ensure a clean python-chess board
    monkeypatch.setattr(gamemanager, "cboard", chess.Board())

    # Provide or override board constants and functions used in fieldcallback
    # Replace LED/beep functions with mocks to assert calls
    monkeypatch.setattr(gamemanager.board, "SOUND_WRONG_MOVE", getattr(gamemanager.board, "SOUND_WRONG_MOVE", "SOUND_WRONG_MOVE"))
    monkeypatch.setattr(gamemanager.board, "beep", MagicMock())
    monkeypatch.setattr(gamemanager.board, "ledsOff", MagicMock())
    monkeypatch.setattr(gamemanager.board, "ledFromTo", MagicMock())
    monkeypatch.setattr(gamemanager.board, "led", MagicMock())

    # Prepare globals used by fieldcallback
    monkeypatch.setattr(gamemanager, "sourcesq", 12)  # e2
    monkeypatch.setattr(gamemanager, "legalsquares", [])
    monkeypatch.setattr(gamemanager, "curturn", 1)
    monkeypatch.setattr(gamemanager, "forcemove", 0)

    return gamemanager


def test_illegal_place_non_takeback_guides_return(monkeypatch):
    gamemanager = _setup_common(monkeypatch)

    # Simulate no takeback
    monkeypatch.setattr(gamemanager, "checkLastBoardState", lambda: False)

    # Place a piece illegally on e4 (index 28)
    piece_event = 1  # PLACE
    field_hex = 0x36  # not used in assertions
    square = 28  # e4
    time_in_seconds = 0.0

    gamemanager.fieldcallback(piece_event, field_hex, square, time_in_seconds)

    gamemanager.board.beep.assert_called()
    gamemanager.board.ledsOff.assert_called_once()
    # Should guide from current square (field) back to source (sourcesq)
    gamemanager.board.ledFromTo.assert_called_once()
    args, kwargs = gamemanager.board.ledFromTo.call_args
    assert args[0] == 28  # from field
    assert args[1] == 12  # to sourcesq


def test_illegal_place_takeback_no_guidance(monkeypatch):
    gamemanager = _setup_common(monkeypatch)

    # Simulate a takeback detected
    monkeypatch.setattr(gamemanager, "checkLastBoardState", lambda: True)

    piece_event = 1  # PLACE
    field_hex = 0x36
    square = 28  # e4
    time_in_seconds = 0.0

    gamemanager.fieldcallback(piece_event, field_hex, square, time_in_seconds)

    # Beep still happens for illegal move, but no LED guidance on takeback
    gamemanager.board.beep.assert_called()
    gamemanager.board.ledFromTo.assert_not_called()
    gamemanager.board.led.assert_not_called()

