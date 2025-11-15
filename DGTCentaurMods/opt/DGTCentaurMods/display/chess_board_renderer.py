"""
Chess board rendering logic separated from display operations.

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

from typing import List, Tuple, Optional
from PIL import Image, ImageDraw
import chess

from DGTCentaurMods.display.display_types import (
    BOARD_SIZE,
    SQUARE_SIZE,
    CHESS_SQUARES,
    PIECE_TO_SPRITE,
    SquareColorOffset,
    COLOR_WHITE,
    COLOR_BLACK
)
from DGTCentaurMods.display.ui_components import AssetManager


class ChessBoardRenderer:
    """
    Handles rendering of chess boards independently of display hardware.
    
    Creates PIL images representing chess positions that can then be
    drawn to the physical display.
    """
    
    def __init__(self):
        """Initialize the chess board renderer."""
        self.chess_sprites: Optional[Image.Image] = None
        self._load_sprites()
    
    def _load_sprites(self) -> None:
        """Load the chess piece sprites from disk."""
        try:
            sprite_path = AssetManager.get_resource_path("chesssprites.bmp")
            self.chess_sprites = Image.open(sprite_path)
        except Exception as e:
            from DGTCentaurMods.board.logging import log
            log.error(f"Failed to load chess sprites: {e}")
            self.chess_sprites = None
    
    def _parse_fen_to_pieces(self, fen: str) -> str:
        """
        Parse a FEN string to a 64-character piece string.
        
        Converts FEN notation into a linear string where each character
        represents a square (space for empty, piece letter for occupied).
        The output is arranged rank 8 to rank 1, left to right.
        
        Args:
            fen: FEN string (only board part is used)
            
        Returns:
            64-character string representing the board
        """
        # Extract just the board part of FEN
        board_fen = fen.split()[0] if ' ' in fen else fen
        
        # Remove rank separators
        board_fen = board_fen.replace("/", "")
        
        # Expand digits to spaces
        for digit in '12345678':
            board_fen = board_fen.replace(digit, ' ' * int(digit))
        
        # Reorder from rank 8 to rank 1 for display
        result = ""
        for rank in range(8, 0, -1):
            for file in range(0, 8):
                result += board_fen[((rank - 1) * 8) + file]
        
        return result
    
    def _is_dark_square(self, row: int, col: int) -> bool:
        """
        Determine if a square is dark based on checkerboard pattern.
        
        Args:
            row: Row index (0-7)
            col: Column index (0-7)
            
        Returns:
            True if square is dark, False if light
        """
        return ((row + col) % 2) == 1
    
    def render_board(
        self,
        pieces: List[str],
        size: Tuple[int, int] = (BOARD_SIZE, BOARD_SIZE),
        flip: bool = False
    ) -> Image.Image:
        """
        Render a chess board from a piece list.
        
        Args:
            pieces: List/string of 64 pieces (rank 8 to rank 1, left to right)
            size: Output image size (default 128x128)
            flip: If True, flip board for black's perspective
            
        Returns:
            PIL Image of the rendered board
        """
        if self.chess_sprites is None:
            # Return blank board if sprites not loaded
            return Image.new('1', size, COLOR_WHITE)
        
        board_image = Image.new('1', size, COLOR_WHITE)
        
        for square_idx in range(CHESS_SQUARES):
            # Calculate position in the display (reversed for display)
            pos = (square_idx - 63) * -1
            row = pos // 8
            col = square_idx % 8
            
            # Calculate pixel coordinates
            pixel_row = row * SQUARE_SIZE
            pixel_col = col * SQUARE_SIZE
            
            # Determine sprite coordinates
            sprite_x = 0
            sprite_y = 0
            
            # Select piece sprite
            piece_char = pieces[square_idx]
            sprite_x = PIECE_TO_SPRITE.get(piece_char, 0)
            
            # Select square color (dark squares use offset +16)
            if self._is_dark_square(row, col):
                sprite_y = SquareColorOffset.DARK
            else:
                sprite_y = SquareColorOffset.LIGHT
            
            # Extract and paste sprite
            sprite = self.chess_sprites.crop((
                sprite_x,
                sprite_y,
                sprite_x + SQUARE_SIZE,
                sprite_y + SQUARE_SIZE
            ))
            
            # Flip if viewing from black's perspective
            if flip:
                pixel_row = (7 - row) * SQUARE_SIZE
                pixel_col = (7 - col) * SQUARE_SIZE
            
            board_image.paste(sprite, (pixel_col, pixel_row))
        
        # Draw border
        draw = ImageDraw.Draw(board_image)
        draw.rectangle(
            [(0, 0), (size[0] - 1, size[1] - 1)],
            fill=None,
            outline=COLOR_BLACK
        )
        
        return board_image
    
    def render_fen(
        self,
        fen: str,
        size: Tuple[int, int] = (BOARD_SIZE, BOARD_SIZE),
        flip: bool = False
    ) -> Image.Image:
        """
        Render a chess board from a FEN string.
        
        Args:
            fen: FEN notation string
            size: Output image size (default 128x128)
            flip: If True, flip board for black's perspective
            
        Returns:
            PIL Image of the rendered board
        """
        pieces = self._parse_fen_to_pieces(fen)
        return self.render_board(pieces, size, flip)
    
    def render_from_chess_board(
        self,
        board: chess.Board,
        size: Tuple[int, int] = (BOARD_SIZE, BOARD_SIZE),
        flip: bool = False
    ) -> Image.Image:
        """
        Render a chess board from a python-chess Board object.
        
        Args:
            board: chess.Board instance
            size: Output image size (default 128x128)
            flip: If True, flip board for black's perspective
            
        Returns:
            PIL Image of the rendered board
        """
        return self.render_fen(board.fen(), size, flip)

