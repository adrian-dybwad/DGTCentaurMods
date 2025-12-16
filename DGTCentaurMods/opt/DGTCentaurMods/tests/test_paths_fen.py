from __future__ import annotations

import DGTCentaurMods.managers.game as game_module


def test_missing_fen_file_returns_default_without_creating_file(tmp_path, monkeypatch):
    """Test that get_current_fen returns default FEN when file is missing.
    
    Expected failure: AssertionError if file is created or wrong FEN returned.
    Why: Verifies graceful handling of missing FEN log file.
    """
    fen_path = tmp_path / "fen.log"
    # Patch FEN_LOG in the game module where it's used
    monkeypatch.setattr(game_module, "FEN_LOG", str(fen_path))

    if fen_path.exists():
        fen_path.unlink()

    result = game_module.get_current_fen()

    assert result == game_module.DEFAULT_START_FEN
    assert not fen_path.exists()


def test_existing_fen_is_preserved(tmp_path, monkeypatch):
    """Test that existing FEN in file is read correctly.
    
    Expected failure: AssertionError if wrong FEN returned or file modified.
    Why: Verifies FEN log reading works correctly.
    """
    fen_path = tmp_path / "fen.log"
    # Patch FEN_LOG in the game module where it's used
    monkeypatch.setattr(game_module, "FEN_LOG", str(fen_path))

    custom_fen = "8/8/8/8/8/8/8/8 w - - 0 1"
    fen_path.parent.mkdir(parents=True, exist_ok=True)
    fen_path.write_text(custom_fen, encoding="utf-8")

    result = game_module.get_current_fen()

    assert result == custom_fen
    assert fen_path.read_text(encoding="utf-8") == custom_fen
