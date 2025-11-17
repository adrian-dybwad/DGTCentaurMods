"""
Chess board widget displaying a chess position from FEN.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import os
import sys

# Import AssetManager - handle both direct execution and module execution
try:
    from DGTCentaurMods.display.ui_components import AssetManager
except ImportError:
    # Fallback for direct execution
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from display.ui_components import AssetManager


class ChessBoardWidget(Widget):
    """Chess board widget that renders a position from FEN string."""
    
    def __init__(self, x: int, y: int, fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", flip: bool = False):
        super().__init__(x, y, 128, 128)
        self.fen = fen
        self.flip = flip
        self._chess_font = None
        self._load_chess_font()
    
    def _load_chess_font(self):
        """Load chess piece sprite sheet."""
        try:
            font_path = AssetManager.get_resource_path("chesssprites.bmp")
            if os.path.exists(font_path):
                self._chess_font = Image.open(font_path)
            else:
                self._chess_font = None
        except Exception:
            self._chess_font = None
    
    def _expand_fen(self, fen_board: str) -> list:
        """Expand FEN board string to 64 characters."""
        rows = fen_board.split("/")
        expanded = []
        for row in rows:
            for char in row:
                if char.isdigit():
                    expanded.extend([" "] * int(char))
                else:
                    expanded.append(char)
        if len(expanded) != 64:
            raise ValueError(f"Invalid FEN: {fen_board}")
        return expanded
    
    def _piece_x(self, piece: str) -> int:
        """Get x coordinate in sprite sheet for piece."""
        mapping = {
            "P": 16,
            "R": 32,
            "N": 48,
            "B": 64,
            "Q": 80,
            "K": 96,
            "p": 112,
            "r": 128,
            "n": 144,
            "b": 160,
            "q": 176,
            "k": 192,
        }
        return mapping.get(piece, 0)
    
    def _is_dark_square(self, index: int) -> bool:
        """Check if square at index is dark."""
        rank = index // 8
        file = index % 8
        return (rank + file) % 2 == 0
    
    def _fade_black_to_grey(self, img: Image.Image) -> Image.Image:
        """Convert black pixels to grey by changing their color value."""
        # Convert to greyscale mode to work with pixel values
        grey_img = img.convert('L')
        width, height = grey_img.size
        
        # Change black pixels (value 0) to grey (value ~128)
        for y in range(height):
            for x in range(width):
                pixel = grey_img.getpixel((x, y))
                if pixel == 0:  # Black pixel
                    grey_img.putpixel((x, y), 128)  # Change to grey
        
        # Convert back to 1-bit mode (will dither appropriately)
        return grey_img.convert('1')
    
    def set_fen(self, fen: str) -> None:
        """Update the FEN string."""
        self.fen = fen
        self._last_rendered = None
    
    def render(self) -> Image.Image:
        """Render chess board."""
        img = Image.new("1", (self.width, self.height), 255)
        
        if self._chess_font is None:
            return img
        
        try:
            fen_board = self.fen.split()[0]
            ordered = self._expand_fen(fen_board)
            draw = ImageDraw.Draw(img)
            
            for idx, symbol in enumerate(ordered):
                rank = idx // 8
                file = idx % 8
                dest_rank = rank if not self.flip else 7 - rank
                dest_file = file if not self.flip else 7 - file
                
                square_index = dest_rank * 8 + dest_file
                is_dark = self._is_dark_square(square_index)
                py = 16 if is_dark else 0
                
                x = dest_file * 16
                y = dest_rank * 16
                
                # Always draw square background (empty square sprite at x=0)
                square_bg = self._chess_font.crop((0, py, 16, py + 16))
                # Fade black squares to grey
                if is_dark:
                    square_bg = self._fade_black_to_grey(square_bg)
                img.paste(square_bg, (x, y))
                
                # Draw piece if it exists
                px = self._piece_x(symbol)
                if px > 0:
                    piece = self._chess_font.crop((px, py, px + 16, py + 16))
                    img.paste(piece, (x, y))
            
            # Draw board outline
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline=0)
        except Exception:
            pass
        
        return img

