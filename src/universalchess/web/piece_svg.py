"""
Chess piece SVG generation utilities for the web UI.

This module provides a small, pure helper around `python-chess`'s SVG rendering
so the web frontend can serve piece images without shipping a full PNG set.
Also provides utilities to convert SVGs to PIL Images for video frame generation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import chess
import chess.svg

if TYPE_CHECKING:
    from PIL import Image as PILImage

try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except ImportError:
    CAIROSVG_AVAILABLE = False


@dataclass(frozen=True)
class PieceSvgOptions:
    """Options for SVG generation.

    Args:
        size: Pixel size for the generated SVG (square).
    """

    size: int = 80


_PIECE_CODES = frozenset({"K", "Q", "R", "B", "N", "P"})
_SVG_CACHE: dict[tuple[str, int], str] = {}
_PIL_CACHE: dict[tuple[str, int], "PILImage.Image"] = {}

# Mapping from FEN piece characters to chessboard.js piece codes
_FEN_TO_PIECE_CODE: dict[str, str] = {
    "K": "wK", "Q": "wQ", "R": "wR", "B": "wB", "N": "wN", "P": "wP",
    "k": "bK", "q": "bQ", "r": "bR", "b": "bB", "n": "bN", "p": "bP",
}


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
    cached = _SVG_CACHE.get(cache_key)
    if cached is not None:
        return cached

    symbol = piece_char.upper() if color_char == "w" else piece_char.lower()
    piece = chess.Piece.from_symbol(symbol)
    svg = chess.svg.piece(piece, size=options.size)

    _SVG_CACHE[cache_key] = svg
    return svg


def generate_piece_image(piece_code: str, size: int = 120) -> "PILImage.Image":
    """Generate a PIL Image for a chessboard.js piece code (e.g., 'wK', 'bQ').
    
    Uses cairosvg to convert the SVG to PNG, then loads as PIL Image.
    Results are cached for performance.

    Args:
        piece_code: chessboard.js piece code: 'wK', 'wQ', 'wR', 'wB', 'wN', 'wP',
            'bK', 'bQ', 'bR', 'bB', 'bN', or 'bP'.
        size: Pixel size for the generated image (square).

    Returns:
        PIL Image in RGBA mode.

    Raises:
        ValueError: If the piece_code is invalid.
        RuntimeError: If cairosvg is not available.
    """
    if not CAIROSVG_AVAILABLE:
        raise RuntimeError(
            "cairosvg is required for piece image generation. "
            "Install with: pip install cairosvg"
        )
    
    from PIL import Image
    
    cache_key = (piece_code, size)
    cached = _PIL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    svg = generate_piece_svg(piece_code, PieceSvgOptions(size=size))
    png_data = cairosvg.svg2png(bytestring=svg.encode("utf-8"))
    image = Image.open(io.BytesIO(png_data)).convert("RGBA")
    
    _PIL_CACHE[cache_key] = image
    return image


def get_piece_images(size: int = 120) -> dict[str, "PILImage.Image"]:
    """Get a dictionary of all piece images keyed by FEN piece character.
    
    This returns a dictionary compatible with the video frame generation code,
    mapping FEN characters (r, b, n, q, k, p, R, B, N, Q, K, P) to PIL Images.

    Args:
        size: Pixel size for the generated images (square).

    Returns:
        Dictionary mapping FEN piece characters to PIL Images.

    Raises:
        RuntimeError: If cairosvg is not available.
    """
    return {
        fen_char: generate_piece_image(piece_code, size)
        for fen_char, piece_code in _FEN_TO_PIECE_CODE.items()
    }


