"""
Base widget class for the ePaper framework.

Widgets only need to implement content rendering. The framework
handles all position tracking, dirty region detection, and refresh scheduling.
"""

from abc import ABC, abstractmethod
from typing import Optional

from PIL import Image


class Widget(ABC):
    """
    Base class for all display widgets.
    
    Widgets implement a render() method that returns a PIL Image.
    The framework automatically tracks widget positions, detects changes,
    computes dirty regions, and schedules refreshes.
    """

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        """
        Initialize widget with position and size.
        
        Args:
            x: X position (left edge)
            y: Y position (top edge)
            width: Widget width in pixels
            height: Widget height in pixels
        """
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self._last_rendered: Optional[Image.Image] = None

    @abstractmethod
    def render(self) -> Image.Image:
        """
        Render the widget content.
        
        Returns:
            PIL Image in mode "1" (1-bit monochrome) with size (width, height)
        """
        pass

    def get_region(self) -> tuple[int, int, int, int]:
        """
        Get widget region as (x1, y1, x2, y2).
        
        Returns:
            Tuple of (x, y, x + width, y + height)
        """
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def has_changed(self) -> bool:
        """
        Check if widget content has changed since last render.
        
        Compares current render output with last cached render.
        """
        current = self.render()
        
        if self._last_rendered is None:
            self._last_rendered = current
            return True
        
        # Compare pixel data
        if current.size != self._last_rendered.size:
            self._last_rendered = current
            return True
        
        if list(current.getdata()) != list(self._last_rendered.getdata()):
            self._last_rendered = current
            return True
        
        return False

    def get_image(self) -> Image.Image:
        """
        Get the current rendered image.
        
        Caches the result for change detection.
        """
        image = self.render()
        self._last_rendered = image
        return image

