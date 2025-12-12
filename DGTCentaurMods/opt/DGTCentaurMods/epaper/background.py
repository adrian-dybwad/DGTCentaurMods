"""
Background widget with dithered grayscale patterns.

On a 1-bit e-paper display, grayscale is simulated using dithering patterns.
This widget provides a full-screen background with configurable shade.
"""

from PIL import Image
from .framework.widget import Widget, DITHER_PATTERNS

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class BackgroundWidget(Widget):
    """Full-screen background widget with dithered grayscale.
    
    Uses ordered dithering to simulate grayscale on 1-bit display.
    Shade levels range from 0 (white) to 16 (black).
    """
    
    def __init__(self, width: int, height: int, shade: int = 0):
        """Create a background widget.
        
        Args:
            width: Display width
            height: Display height
            shade: Grayscale level 0-16 (0=white, 8=50% gray, 16=black)
        """
        super().__init__(0, 0, width, height, background_shade=shade)
        self._cached_image = None
    
    def set_shade(self, shade: int) -> None:
        """Set the background shade level.
        
        Args:
            shade: Grayscale level 0-16 (0=white, 8=50% gray, 16=black)
        """
        shade = max(0, min(16, shade))
        if shade != self._background_shade:
            self._background_shade = shade
            self._cached_image = None
            self.request_update(full=False)
    
    def render(self) -> Image.Image:
        """Render the dithered background pattern."""
        # Use cached image if available
        if self._cached_image is not None:
            return self._cached_image
        
        self._cached_image = self.create_background_image()
        return self._cached_image
