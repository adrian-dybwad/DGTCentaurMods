"""
Base widget class for ePaper display.
"""

from abc import ABC, abstractmethod
from PIL import Image
from typing import Optional, TYPE_CHECKING, Callable
from .regions import Region

if TYPE_CHECKING:
    from .scheduler import Scheduler


class Widget(ABC):
    """Base class for all display widgets."""
    
    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self._last_rendered: Optional[Image.Image] = None
        self._scheduler: Optional['Scheduler'] = None
        self._update_callback: Optional[Callable[[bool], object]] = None
    
    def set_scheduler(self, scheduler: 'Scheduler') -> None:
        """Set the scheduler for this widget to trigger updates."""
        self._scheduler = scheduler
    
    def set_update_callback(self, callback: Callable[[bool], object]) -> None:
        """Set a callback to trigger Manager.update() when widget state changes.
        
        The callback should accept a 'full' boolean parameter and return a Future.
        This allows widgets to trigger full update cycles that render all widgets.
        """
        self._update_callback = callback
    
    def get_scheduler(self) -> Optional['Scheduler']:
        """Get the scheduler for this widget."""
        return self._scheduler
    
    def request_update(self, full: bool = False):
        """Request a display update.
        
        This method should be called by widgets when their state changes
        and they need the display to refresh. It will:
        1. Call the update callback (Manager.update()) to render all widgets
        2. The callback internally submits to the scheduler
        
        Args:
            full: If True, force a full refresh instead of partial refresh.
        
        Returns:
            Future: A Future that completes when the display refresh finishes.
            Returns None if update callback is not available.
        """
        if self._update_callback is not None:
            return self._update_callback(full)
        # Fallback: if no callback, try direct scheduler submission
        # (but this won't render widgets, so content may be stale)
        if self._scheduler is not None:
            return self._scheduler.submit(full=full)
        return None
    
    def get_region(self) -> Region:
        """Get the widget's display region."""
        return Region(self.x, self.y, self.x + self.width, self.y + self.height)
    
    @abstractmethod
    def render(self) -> Image.Image:
        """Render the widget content. Must return an image of size (width, height)."""
        pass
    
    def get_mask(self) -> Optional[Image.Image]:
        """Get a mask for transparent compositing. Returns None if not needed."""
        return None
