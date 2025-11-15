"""
Type definitions, constants, and enums for e-paper display operations.

This file is part of the DGTCentaur Mods open source software
( https://github.com/EdNekebno/DGTCentaur )

DGTCentaur Mods is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

DGTCentaur Mods is distributed in the hope that it will
be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this file.  If not, see

https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md

This and any other notices must remain intact and unaltered in any
distribution, modification, variant, or derivative of this software.
"""

from enum import Enum, IntEnum
from typing import Tuple
from PIL import Image

# Display dimensions (Waveshare 2.9" e-paper)
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 296

# Row height for text display
ROW_HEIGHT = 20

# Display regions
STATUSBAR_ROW = 0
TITLE_ROW = 1
CONTENT_START_ROW = 2
BOARD_START_ROW = 2

# Chess board constants
BOARD_SIZE = 128  # pixels (8x8 board with 16px squares)
SQUARE_SIZE = 16  # pixels per square
CHESS_SQUARES = 64

# Color constants (for 1-bit display)
COLOR_WHITE = 255
COLOR_BLACK = 0

# Update modes
class UpdateMode(IntEnum):
    """Display update modes."""
    PARTIAL = 0  # Fast partial update (optimized for small changes)
    FULL = 1     # Full screen refresh (slower but cleaner)


class DisplayState(Enum):
    """Display manager operational states."""
    UNINITIALIZED = "uninitialized"
    INITIALIZED = "initialized"
    PAUSED = "paused"
    SLEEPING = "sleeping"
    DISABLED = "disabled"


# Sleep timeout (in 100ms increments, 15000 = 1500 seconds = 25 minutes)
SLEEP_TIMEOUT_COUNT = 15000

# Sprite offsets in chesssprites.bmp
class PieceSpriteOffset(IntEnum):
    """Horizontal pixel offsets for piece sprites."""
    EMPTY = 0
    WHITE_PAWN = 16
    WHITE_ROOK = 32
    WHITE_KNIGHT = 48
    WHITE_BISHOP = 64
    WHITE_QUEEN = 80
    WHITE_KING = 96
    BLACK_PAWN = 112
    BLACK_ROOK = 128
    BLACK_KNIGHT = 144
    BLACK_BISHOP = 160
    BLACK_QUEEN = 176
    BLACK_KING = 192


class SquareColorOffset(IntEnum):
    """Vertical pixel offsets for square colors in sprites."""
    LIGHT = 0   # White/light squares
    DARK = 16   # Gray/dark squares


# Piece character to sprite offset mapping
PIECE_TO_SPRITE = {
    ' ': PieceSpriteOffset.EMPTY,
    'P': PieceSpriteOffset.WHITE_PAWN,
    'R': PieceSpriteOffset.WHITE_ROOK,
    'N': PieceSpriteOffset.WHITE_KNIGHT,
    'B': PieceSpriteOffset.WHITE_BISHOP,
    'Q': PieceSpriteOffset.WHITE_QUEEN,
    'K': PieceSpriteOffset.WHITE_KING,
    'p': PieceSpriteOffset.BLACK_PAWN,
    'r': PieceSpriteOffset.BLACK_ROOK,
    'n': PieceSpriteOffset.BLACK_KNIGHT,
    'b': PieceSpriteOffset.BLACK_BISHOP,
    'q': PieceSpriteOffset.BLACK_QUEEN,
    'k': PieceSpriteOffset.BLACK_KING,
}


# Type aliases for clarity
BufferType = Image.Image
CoordinateType = Tuple[int, int]
RegionType = Tuple[int, int, int, int]  # (x1, y1, x2, y2)


# GPIO Pin definitions for Raspberry Pi
class RPiPins(IntEnum):
    """GPIO pin assignments for Raspberry Pi."""
    RST_PIN = 12
    DC_PIN = 16
    CS_PIN = 18
    BUSY_PIN = 13


# GPIO Pin definitions for Jetson Nano
class JetsonPins(IntEnum):
    """GPIO pin assignments for Jetson Nano."""
    RST_PIN = 17
    DC_PIN = 25
    CS_PIN = 8
    BUSY_PIN = 24


# Battery indicator thresholds
class BatteryLevel(IntEnum):
    """Battery level thresholds for indicator icons."""
    CRITICAL = 0
    LOW = 6
    MEDIUM = 12
    HIGH = 18
    FULL = 20

