"""
Chess piece SVG generation utilities for the web UI.

This module provides a small, pure helper around `python-chess`'s SVG rendering
so the web frontend can serve piece images without shipping a full PNG set.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess
import chess.svg


@dataclass(frozen=True)
class PieceSvgOptions:
    """Options for SVG generation.

    Args:
        size: Pixel size for the generated SVG (square).
    """

    size: int = 80


_PIECE_CODES = frozenset({"K", "Q", "R", "B", "N", "P"})
_CACHE: dict[tuple[str, int], str] = {}


def generate_piece_svg(piece_code: str, options: PieceSvgOptions | None = None) -> str:
    """Generate an SVG for a chessboard.js piece code (e.g., 'wK', 'bQ').

    Args:
        piece_code: chessboard.js piece code: 'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
            'bK', 'bQ', 'bR', 'bB', 'bN', or 'bP'.
        options: Optional SVG options (size).

    Returns:
        SVG XML string.

    Raises:
        ValueError: If the piece_code is invalid.
    """

    if options is None:
        options = PieceSvgOptions()

    if len(piece_code) != 2:
        raise ValueError(f"Invalid piece code: {piece_code!r} (expected length 2)")

    color_char = piece_code[0]
    piece_char = piece_code[1]

    if color_char not in {"w", "b"}:
        raise ValueError(f"Invalid piece code: {piece_code!r} (expected 'w' or 'b' prefix)")

    if piece_char not in _PIECE_CODES:
        raise ValueError(f"Invalid piece code: {piece_code!r} (expected one of KQRNBP)")

    cache_key = (piece_code, options.size)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    symbol = piece_char.upper() if color_char == "w" else piece_char.lower()
    piece = chess.Piece.from_symbol(symbol)
    svg = chess.svg.piece(piece, size=options.size)

    _CACHE[cache_key] = svg
    return svg


