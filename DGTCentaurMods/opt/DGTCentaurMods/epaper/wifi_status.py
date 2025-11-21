"""
WiFi status indicator widget.
"""

from PIL import Image, ImageDraw
from .framework.widget import Widget

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    from DGTCentaurMods.board import network
except ImportError:
    network = None


class WiFiStatusWidget(Widget):
    """WiFi status indicator widget showing connection state."""
    
    def __init__(self, x: int, y: int):
        super().__init__(x, y, 16, 16)
    
    def _is_connected(self) -> bool:
        """Check if WiFi is connected."""
        try:
            if network is None:
                return False
            result = network.check_network()
            return result is not False and result is not None
        except Exception as e:
            log.debug(f"Error checking WiFi status: {e}")
            return False
    
    def render(self) -> Image.Image:
        """Render WiFi status icon."""
        img = Image.new("1", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        
        is_connected = self._is_connected()
        
        if is_connected:
            # Draw connected WiFi icon (3 curved lines)
            # Top arc (signal strength 3/3)
            draw.arc([2, 2, 14, 14], start=45, end=135, fill=0, width=1)
            # Middle arc (signal strength 2/3)
            draw.arc([4, 4, 12, 12], start=45, end=135, fill=0, width=1)
            # Bottom arc (signal strength 1/3)
            draw.arc([6, 6, 10, 10], start=45, end=135, fill=0, width=1)
            # Dot in center
            draw.ellipse([7, 7, 9, 9], fill=0)
        else:
            # Draw disconnected WiFi icon (X with curved lines)
            # Top arc (faded)
            draw.arc([2, 2, 14, 14], start=45, end=135, fill=0, width=1)
            # Middle arc (faded)
            draw.arc([4, 4, 12, 12], start=45, end=135, fill=0, width=1)
            # X mark
            draw.line([2, 2, 14, 14], fill=0, width=1)
            draw.line([14, 2, 2, 14], fill=0, width=1)
        
        return img

