"""
E-paper display compatibility layer (DEPRECATED - Use DisplayManager directly).

This module provides backward compatibility by wrapping DisplayManager.
New code should import and use display_manager directly from display_manager module.

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

from typing import List
from PIL import Image

# Import the new display manager
from DGTCentaurMods.display.display_manager import display_manager
from DGTCentaurMods.display.display_types import UpdateMode, BOARD_START_ROW

# For backward compatibility, expose the global buffer
# Note: This returns a COPY, modifications won't affect display
epaperbuffer = display_manager.get_buffer()

# Status bar class wrapper
class statusBar:
    """Compatibility wrapper for statusBar class."""
    
    def __init__(self):
        self.is_running = False
    
    def build(self):
        """Build status bar string."""
        import time
        return time.strftime("%H:%M")
    
    def display(self):
        """Display status bar in a loop (runs in thread)."""
        import time
        while self.is_running:
            display_manager.draw_status_bar()
            time.sleep(30)
    
    def print(self):
        """Print status bar once."""
        display_manager.draw_status_bar()
    
    def init(self):
        """Initialize status bar thread."""
        import threading
        from DGTCentaurMods.board.logging import log
        log.debug("Starting status bar update thread")
        self.statusbar = threading.Thread(target=self.display, args=())
        self.statusbar.daemon = True
        self.statusbar.start()
    
    def start(self):
        """Start status bar updates."""
        self.is_running = True
        self.init()
    
    def stop(self):
        """Stop status bar updates."""
        from DGTCentaurMods.board.logging import log
        log.debug("Kill status bar thread")
        self.is_running = False


# Menu drawing class wrapper
class MenuDraw:
    """Compatibility wrapper for MenuDraw class."""
    
    def __init__(self):
        self.statusbar = statusBar()
    
    def draw_page(self, title: str, items: List[str]):
        """Draw a menu page."""
        from DGTCentaurMods.board.logging import log
        log.debug('-------------')
        log.debug(title)
        log.debug('-------------')
        
        display_manager.clear()
        display_manager.draw_menu_title(title)
        
        row = 2
        for item in items:
            display_manager.draw_text(row, "  " + item)
            log.debug(item)
            row += 1
        
        self.statusbar.print()
    
    def highlight(self, index: int, rollaround: int = 0):
        """
        Highlight a menu item.
        
        Note: This uses direct EPD commands which may not work with new architecture.
        Consider reimplementing with DisplayManager methods.
        """
        from DGTCentaurMods.board.logging import log
        log.warning("MenuDraw.highlight() uses deprecated direct EPD access - may not work correctly")
        # This function uses direct epd commands which bypasses DisplayManager
        # Keeping stub for compatibility but it may not work correctly


# === Compatibility Functions ===

def initEpaper(mode: int = 0):
    """
    Initialize e-paper display.
    
    Args:
        mode: Update mode (0=PARTIAL, 1=FULL)
    """
    update_mode = UpdateMode.PARTIAL if mode == 0 else UpdateMode.FULL
    display_manager.initialize(update_mode)


def pauseEpaper():
    """Pause display updates."""
    display_manager.pause()


def unPauseEpaper():
    """Resume display updates."""
    display_manager.resume()


def stopEpaper():
    """Stop the display (show QR code and shutdown)."""
    from DGTCentaurMods.display.ui_components import AssetManager
    from PIL import Image
    import time
    
    # Show logo and QR code
    filename = AssetManager.get_resource_path("logo_mods_screen.jpg")
    lg = Image.open(filename)
    lgs = Image.new('1', (128, 296), 255)
    lgs.paste(lg, (0, 0))
    
    qrfile = AssetManager.get_resource_path("qr-support.png")
    qr = Image.open(qrfile)
    qr = qr.resize((128, 128))
    lgs.paste(qr, (0, 160))
    
    display_manager.draw_image(0, 0, lgs)
    time.sleep(3)
    
    display_manager.shutdown()


def killEpaper():
    """Kill the display update thread."""
    display_manager.shutdown()


def writeText(row: int, txt: str):
    """
    Write text on a row.
    
    Args:
        row: Row number (0-14)
        txt: Text to display
    """
    display_manager.draw_text(row, txt)


def writeMenuTitle(title: str):
    """
    Write menu title (inverted).
    
    Args:
        title: Title text
    """
    display_manager.draw_menu_title(title)


def drawRectangle(x1: int, y1: int, x2: int, y2: int, fill: int, outline: int):
    """Draw a rectangle."""
    display_manager.draw_rectangle(x1, y1, x2, y2, fill, outline)


def clearArea(x1: int, y1: int, x2: int, y2: int):
    """Clear an area (draw white rectangle)."""
    display_manager.draw_rectangle(x1, y1, x2, y2, 255, 255)


def clearScreen():
    """Clear the screen to white."""
    display_manager.clear()


def drawBoard(pieces: List[str], startrow: int = BOARD_START_ROW):
    """
    Draw a chess board.
    
    Args:
        pieces: List/string of 64 pieces
        startrow: Starting row (default 2)
    """
    display_manager.draw_board(pieces, startrow)


def drawFen(fen: str, startrow: int = BOARD_START_ROW):
    """
    Draw a chess board from FEN.
    
    Args:
        fen: FEN notation string
        startrow: Starting row (default 2)
    """
    display_manager.draw_fen(fen, startrow)


def promotionOptions(row: int):
    """Draw promotion options."""
    display_manager.draw_promotion_options(row)


def resignDrawMenu(row: int):
    """Draw resign/draw menu."""
    display_manager.draw_resign_draw_menu(row)


def quickClear():
    """Quick clear (assumes partial mode)."""
    display_manager.quick_clear()


def drawImagePartial(x: int, y: int, img: Image.Image):
    """
    Draw an image at position.
    
    Args:
        x: X coordinate
        y: Y coordinate
        img: PIL Image
    """
    display_manager.draw_image(x, y, img)


def drawBatteryIndicator():
    """Draw battery indicator."""
    display_manager.draw_battery_indicator()


def loadingScreen():
    """Show loading screen."""
    display_manager.show_loading_screen()


def welcomeScreen():
    """Show welcome screen."""
    display_manager.show_welcome_screen()


def standbyScreen(show: bool):
    """
    Show or hide standby screen.
    
    Args:
        show: True to show standby, False to restore
    """
    display_manager.show_standby_screen(show)


def refresh():
    """Force a display refresh (deprecated, no-op)."""
    display_manager.refresh()


def drawWindow(x: int, y: int, w: int, data: bytes):
    """
    Draw a window using raw byte data (DEPRECATED).
    
    This function is deprecated and may not work correctly with new architecture.
    """
    from DGTCentaurMods.board.logging import log
    log.warning("drawWindow() is deprecated and may not work correctly with new display architecture")
