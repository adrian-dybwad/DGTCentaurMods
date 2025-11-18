"""
Chess board widget displaying a chess position from FEN.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget
import os
import sys
import logging

logger = logging.getLogger(__name__)

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
        logger.debug("Attempting to load chesssprites sprite sheet")
        
        try:
            font_path = AssetManager.get_resource_path("chesssprites_fen.bmp")
            logger.debug(f"Resolved chesssprites path: {font_path}")
            
            if not font_path:
                logger.error("AssetManager.get_resource_path() returned empty path for chesssprites_fen.bmp")
                self._chess_font = None
                return
            
            if not os.path.exists(font_path):
                logger.error(f"Chesssprites file not found at path: {font_path}")
                self._chess_font = None
                return
            
            logger.debug(f"Chesssprites file exists, attempting to open: {font_path}")
            
            try:
                self._chess_font = Image.open(font_path)
                logger.debug(f"Successfully opened chesssprites image")
            except IOError as e:
                logger.error(f"IOError opening chesssprites file {font_path}: {e}")
                self._chess_font = None
                return
            except OSError as e:
                logger.error(f"OSError opening chesssprites file {font_path}: {e}")
                self._chess_font = None
                return
            except Exception as e:
                logger.error(f"Unexpected error opening chesssprites file {font_path}: {type(e).__name__}: {e}")
                self._chess_font = None
                return
            
            # Validate image dimensions
            if self._chess_font is not None:
                width, height = self._chess_font.size
                mode = self._chess_font.mode
                logger.debug(f"Chesssprites image loaded: {width}x{height}, mode={mode}")
                
                # Sprite sheet should be at least 208x32 (13 pieces * 16px width, 2 rows * 16px height)
                if width < 208 or height < 32:
                    logger.warning(
                        f"Chesssprites image dimensions {width}x{height} are smaller than expected "
                        f"(minimum 208x32). Sprite sheet may be incomplete."
                    )
                else:
                    logger.debug(f"Chesssprites image dimensions validated: {width}x{height}")
        except Exception as e:
            logger.error(f"Unexpected error in _load_chess_font(): {type(e).__name__}: {e}", exc_info=True)
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
    
    def _validate_crop_coords(self, x1: int, y1: int, x2: int, y2: int) -> bool:
        """Validate crop coordinates are within sprite sheet bounds."""
        if self._chess_font is None:
            logger.warning("Cannot validate crop coordinates: chess font not loaded")
            return False
        
        sheet_width, sheet_height = self._chess_font.size
        
        if x1 < 0 or y1 < 0 or x2 > sheet_width or y2 > sheet_height:
            logger.warning(
                f"Crop coordinates out of bounds: requested ({x1}, {y1}, {x2}, {y2}), "
                f"sprite sheet size: {sheet_width}x{sheet_height}"
            )
            return False
        
        if x1 >= x2 or y1 >= y2:
            logger.warning(
                f"Invalid crop coordinates: x1={x1} >= x2={x2} or y1={y1} >= y2={y2}"
            )
            return False
        
        return True
    
    def set_fen(self, fen: str) -> None:
        """Update the FEN string."""
        self.fen = fen
        self._last_rendered = None
    
    def render(self) -> Image.Image:
        """Render chess board."""
        img = Image.new("1", (self.width, self.height), 255)
        
        if self._chess_font is None:
            logger.warning("Cannot render chess board: chess font not loaded")
            return img
        
        # Parse FEN
        try:
            fen_board = self.fen.split()[0]
            logger.debug(f"Parsing FEN board string: {fen_board}")
        except (AttributeError, IndexError) as e:
            logger.error(f"Error parsing FEN string '{self.fen}': {type(e).__name__}: {e}")
            return img
        
        # Expand FEN to 64 characters
        try:
            ordered = self._expand_fen(fen_board)
            logger.debug(f"FEN expanded to {len(ordered)} squares")
        except ValueError as e:
            logger.error(f"Invalid FEN board string '{fen_board}': {e}")
            return img
        except Exception as e:
            logger.error(f"Unexpected error expanding FEN '{fen_board}': {type(e).__name__}: {e}")
            return img
        
        draw = ImageDraw.Draw(img)
        sheet_width, sheet_height = self._chess_font.size
        
        # Render each square
        for idx, symbol in enumerate(ordered):
            try:
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
                bg_x1, bg_y1, bg_x2, bg_y2 = 0, py, 16, py + 16
                if not self._validate_crop_coords(bg_x1, bg_y1, bg_x2, bg_y2):
                    logger.error(
                        f"Invalid background crop coordinates for square {idx} "
                        f"(rank={rank}, file={file}): ({bg_x1}, {bg_y1}, {bg_x2}, {bg_y2})"
                    )
                    continue
                
                try:
                    square_bg = self._chess_font.crop((bg_x1, bg_y1, bg_x2, bg_y2))
                except Exception as e:
                    logger.error(
                        f"Error cropping square background at ({bg_x1}, {bg_y1}, {bg_x2}, {bg_y2}): "
                        f"{type(e).__name__}: {e}"
                    )
                    continue
                
                try:
                    img.paste(square_bg, (x, y))
                except Exception as e:
                    logger.error(
                        f"Error pasting square background at ({x}, {y}): {type(e).__name__}: {e}"
                    )
                    continue
                
                # Draw piece if it exists
                px = self._piece_x(symbol)
                if px > 0:
                    piece_x1, piece_y1, piece_x2, piece_y2 = px, py, px + 16, py + 16
                    if not self._validate_crop_coords(piece_x1, piece_y1, piece_x2, piece_y2):
                        logger.warning(
                            f"Invalid piece crop coordinates for symbol '{symbol}' at square {idx}: "
                            f"({piece_x1}, {piece_y1}, {piece_x2}, {piece_y2})"
                        )
                        continue
                    
                    try:
                        piece = self._chess_font.crop((piece_x1, piece_y1, piece_x2, piece_y2))
                    except Exception as e:
                        logger.error(
                            f"Error cropping piece '{symbol}' at ({piece_x1}, {piece_y1}, {piece_x2}, {piece_y2}): "
                            f"{type(e).__name__}: {e}"
                        )
                        continue
                    
                    try:
                        img.paste(piece, (x, y))
                    except Exception as e:
                        logger.error(
                            f"Error pasting piece '{symbol}' at ({x}, {y}): {type(e).__name__}: {e}"
                        )
                        continue
            except Exception as e:
                logger.error(
                    f"Unexpected error rendering square {idx} (symbol='{symbol}'): "
                    f"{type(e).__name__}: {e}"
                )
                continue
        
        # Draw board outline
        try:
            draw.rectangle([(0, 0), (127, 127)], fill=None, outline=0)
        except Exception as e:
            logger.error(f"Error drawing board outline: {type(e).__name__}: {e}")
        
        return img

