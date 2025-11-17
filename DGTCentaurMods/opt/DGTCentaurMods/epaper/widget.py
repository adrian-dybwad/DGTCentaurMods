"""
Base widget class for ePaper display.
"""

from abc import ABC, abstractmethod
from PIL import Image
from typing import Optional, Tuple
from .regions import Region


class Widget(ABC):
    """Base class for all display widgets."""
    
    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self._last_rendered: Optional[Image.Image] = None
    
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
