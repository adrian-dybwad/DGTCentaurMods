from __future__ import annotations

from DGTCentaurMods.config import paths


def test_missing_fen_file_returns_default_without_creating_file(tmp_path, monkeypatch):
    fen_path = tmp_path / "fen.log"
    monkeypatch.setattr(paths, "FEN_LOG", str(fen_path), raising=True)

    if fen_path.exists():
        fen_path.unlink()

    result = paths.get_current_fen()

    assert result == paths.DEFAULT_START_FEN
    assert not fen_path.exists()


def test_get_current_placement_works_when_missing(tmp_path, monkeypatch):
    fen_path = tmp_path / "fen.log"
    monkeypatch.setattr(paths, "FEN_LOG", str(fen_path), raising=True)

    if fen_path.exists():
        fen_path.unlink()

    placement = paths.get_current_placement()

    assert placement == paths.DEFAULT_START_FEN.split(" ")[0]


def test_existing_fen_is_preserved(tmp_path, monkeypatch):
    fen_path = tmp_path / "fen.log"
    monkeypatch.setattr(paths, "FEN_LOG", str(fen_path), raising=True)

    custom_fen = "8/8/8/8/8/8/8/8 w - - 0 1"
    fen_path.parent.mkdir(parents=True, exist_ok=True)
    fen_path.write_text(custom_fen, encoding="utf-8")

    result = paths.get_current_fen()

    assert result == custom_fen
    assert fen_path.read_text(encoding="utf-8") == custom_fen


