"""
Tests for on-the-fly SVG generation used by the web UI.
"""

import pytest

from universalchess.web.piece_svg import generate_piece_svg


@pytest.mark.parametrize(
    "piece_code",
    ["wK", "wQ", "wR", "wB", "wN", "wP", "bK", "bQ", "bR", "bB", "bN", "bP"],
)
def test_generate_piece_svg_should_return_svg_xml(piece_code: str):
    # Expected failure message: missing <svg> output
    # Why: chessboard.js requires a valid image payload to render pieces.
    svg = generate_piece_svg(piece_code)
    assert "<svg" in svg and "</svg>" in svg


@pytest.mark.parametrize("piece_code", ["", "w", "K", "xK", "wX", "bb", "w1", "b0"])
def test_generate_piece_svg_should_reject_invalid_piece_codes(piece_code: str):
    # Expected failure message: invalid piece code accepted
    # Why: the web route must not accept arbitrary paths/inputs.
    with pytest.raises(ValueError):
        generate_piece_svg(piece_code)


