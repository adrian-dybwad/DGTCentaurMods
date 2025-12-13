"""
Base widget class for ePaper display.
"""

from abc import ABC, abstractmethod
from PIL import Image
from typing import Optional, TYPE_CHECKING, Callable
import random

if TYPE_CHECKING:
    from .scheduler import Scheduler

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# Random noise dithering pattern size
# Using 128x128 provides good coverage without excessive memory usage
_NOISE_PATTERN_SIZE = 128

# Pre-computed random noise threshold matrix (values 0-255)
# Uses a fixed seed for deterministic results across renders, which is
# critical for e-paper displays to avoid flicker from varying patterns.
# Random noise dithering produces a grainy but natural-looking result
# without the regular grid artifacts of Bayer ordered dithering.
def _generate_random_noise_matrix() -> list:
    """Generate a random noise threshold matrix.
    
    Uses a fixed seed for deterministic results across renders, which is
    critical for e-paper displays to avoid flicker from varying patterns.
    
    Returns:
        128x128 list of random values 0-255
    """
    # Use fixed seed for deterministic pattern generation
    rng = random.Random(42)
    matrix = []
    for _ in range(_NOISE_PATTERN_SIZE):
        row = [rng.randint(0, 255) for _ in range(_NOISE_PATTERN_SIZE)]
        matrix.append(row)
    return matrix


# Pre-generate the random noise matrix once at module load
_RANDOM_NOISE = _generate_random_noise_matrix()


def _generate_dither_pattern(shade: int) -> list:
    """Generate a 128x128 dither pattern for a given shade level using random noise.
    
    Random noise dithering produces a grainy but natural-looking result without
    regular grid artifacts. The pattern is deterministic due to fixed seed.
    
    Args:
        shade: Shade level 0-16 (0=white, 16=black)
        
    Returns:
        128x128 list of 0s (white) and 1s (black)
    """
    # Map shade 0-16 to threshold 0-256
    # shade 0 = threshold 0 (all white)
    # shade 16 = threshold 256 (all black)
    threshold = shade * 16  # 0, 16, 32, ... 256
    
    pattern = []
    for row in _RANDOM_NOISE:
        pattern_row = []
        for val in row:
            # Pixel is black if random noise value is less than threshold
            pattern_row.append(1 if val < threshold else 0)
        pattern.append(pattern_row)
    return pattern


# Pre-generate patterns for shade levels 0-16
DITHER_PATTERNS = {shade: _generate_dither_pattern(shade) for shade in range(17)}


class Widget(ABC):
    """Base class for all display widgets."""
    
    # Class-level flag indicating if this widget type is modal.
    # When a modal widget is present, only it is rendered.
    is_modal: bool = False
    
    def __init__(self, x: int, y: int, width: int, height: int, background_shade: int = 0):
        """Initialize a widget.
        
        Args:
            x: X position on display
            y: Y position on display
            width: Widget width in pixels
            height: Widget height in pixels
            background_shade: Dithered background shade 0-16 (0=white, 8=50% gray, 16=black)
        """
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.visible = True  # Whether the widget should be rendered by the Manager
        self._background_shade = max(0, min(16, background_shade))
        self._last_rendered: Optional[Image.Image] = None
        self._scheduler: Optional['Scheduler'] = None
        self._update_callback: Optional[Callable[[bool], object]] = None
        log.debug(f"Widget.__init__(): Created {self.__class__.__name__} instance id={id(self)} at ({x}, {y}) size {width}x{height}")
    
    def set_scheduler(self, scheduler: 'Scheduler') -> None:
        """Set the scheduler for this widget to trigger updates."""
        self._scheduler = scheduler
        log.debug(f"Widget.set_scheduler(): {self.__class__.__name__} id={id(self)} scheduler set")
    
    def set_update_callback(self, callback: Callable[[bool], object]) -> None:
        """Set a callback to trigger Manager.update() when widget state changes.
        
        The callback should accept a 'full' boolean parameter and return a Future.
        This allows widgets to trigger full update cycles that render all widgets.
        """
        self._update_callback = callback
        log.debug(f"Widget.set_update_callback(): {self.__class__.__name__} id={id(self)} update callback set")
            
    def get_scheduler(self) -> Optional['Scheduler']:
        """Get the scheduler for this widget."""
        return self._scheduler
    
    def request_update(self, full: bool = False, forced: bool = False):
        """Request a display update.
        
        This method should be called by widgets when their state changes
        and they need the display to refresh. It calls Manager.update() which:
        1. Renders all widgets to the framebuffer
        2. Submits the complete framebuffer to the scheduler
        
        If the widget is not visible and forced is False, the request is ignored
        since hidden widgets are not rendered and would cause unnecessary update cycles.
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
            forced: If True, ignore visibility check (used by show/hide to update display).
        
        Returns:
            Future: A Future that completes when the display refresh finishes.
            Returns None if update callback is not available or widget is hidden.
        
        Note:
            Widgets should NOT call the scheduler directly. The Manager must
            render all widgets first before submitting to ensure consistent state.
        """
        # Ignore update requests from hidden widgets (unless forced)
        if not self.visible and not forced:
            log.debug(f"Widget.request_update(): {self.__class__.__name__} id={id(self)} ignored (widget is hidden)")
            return None
        
        if full:
            log.warning(f"Widget.request_update(): {self.__class__.__name__} requesting FULL refresh (will cause flashing)")
        else:
            log.debug(f"Widget.request_update(): {self.__class__.__name__} id={id(self)} requesting partial update")
        
        if self._update_callback is not None:
            return self._update_callback(full)
        
        # No callback available - cannot update without Manager
        log.debug(f"Widget.request_update(): {self.__class__.__name__} id={id(self)} ignored (no update callback)")
        return None
    
    def set_background_shade(self, shade: int) -> None:
        """Set the background shade level.
        
        Args:
            shade: Grayscale level 0-16 (0=white, 8=50% gray, 16=black)
        """
        shade = max(0, min(16, shade))
        if shade != self._background_shade:
            self._background_shade = shade
            self._last_rendered = None
            self.request_update(full=False)
    
    def create_background_image(self) -> Image.Image:
        """Create a new image with the widget's dithered background.
        
        Subclasses should call this at the start of render() instead of
        Image.new("1", (self.width, self.height), 255) to get a dithered
        background based on background_shade.
        
        Uses random noise dithering, which provides a natural grainy appearance
        without the regular grid artifacts of Bayer ordered dithering.
        
        Returns:
            A new 1-bit image with the dithered background pattern applied.
        """
        img = Image.new("1", (self.width, self.height), 255)
        
        if self._background_shade == 0:
            return img  # Pure white, no dithering needed
        
        pattern = DITHER_PATTERNS.get(self._background_shade, DITHER_PATTERNS[0])
        pixels = img.load()
        for y in range(self.height):
            pattern_row = pattern[y % _NOISE_PATTERN_SIZE]
            for x in range(self.width):
                if pattern_row[x % _NOISE_PATTERN_SIZE] == 1:
                    pixels[x, y] = 0  # Black pixel
        
        return img
    
    @abstractmethod
    def render(self) -> Image.Image:
        """Render the widget content. Must return an image of size (width, height)."""
        pass
    
    def get_mask(self) -> Optional[Image.Image]:
        """Get a mask for transparent compositing. Returns None if not needed."""
        return None
    
    def show(self) -> None:
        """Show the widget (make it visible).
        
        When visible, the widget will be rendered by the Manager.
        Triggers a display update to reflect the change.
        """
        if not self.visible:
            self.visible = True
            self._last_rendered = None  # Force re-render
            log.info(f"Widget.show(): {self.__class__.__name__} id={id(self)} now visible")
            self.request_update(full=False, forced=True)
    
    def hide(self) -> None:
        """Hide the widget (make it invisible).
        
        When hidden, the widget will not be rendered by the Manager.
        The widget remains in the display manager and continues any
        background processing (e.g., analysis), but its region on the
        display will be left for other widgets or background.
        Triggers a display update to reflect the change.
        """
        if self.visible:
            self.visible = False
            self._last_rendered = None
            log.info(f"Widget.hide(): {self.__class__.__name__} id={id(self)} now hidden")
            self.request_update(full=False, forced=True)
    
    def stop(self) -> None:
        """Stop the widget and perform cleanup tasks.
        
        This method should be overridden by widgets that have background threads,
        timers, or other resources that need cleanup. The default implementation
        does nothing.
        
        This method is called by Manager.shutdown() to ensure proper cleanup
        of all widgets before the display is shut down.
        """
        log.debug(f"Widget.stop(): {self.__class__.__name__} id={id(self)} stop() called")