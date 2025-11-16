"""
Framebuffer with automatic dirty region tracking via image diffing.
"""

import threading
from typing import Optional

from PIL import Image

from .regions import Region


class FrameBuffer:
    """
    Maintains a shadow framebuffer and tracks dirty regions.
    
    The framebuffer uses image diffing to automatically detect changes
    between the current state and the last flushed state.
    """

    def __init__(self, width: int = 128, height: int = 296) -> None:
        self.width = width
        self.height = height
        
        # Current working buffer (what widgets draw to)
        self._current = Image.new("1", (width, height), 255)
        
        # Last flushed buffer (what's actually on the display)
        self._flushed = Image.new("1", (width, height), 255)
        
        self._lock = threading.RLock()

    def get_canvas(self) -> Image.Image:
        """
        Get the current canvas for drawing.
        
        Widgets should draw to this image. The framework will
        automatically detect changes via diffing.
        """
        with self._lock:
            return self._current

    def snapshot(self) -> Image.Image:
        """Get a snapshot of the current buffer."""
        with self._lock:
            return self._current.copy()

    def snapshot_region(self, region: Region) -> Image.Image:
        """Get a snapshot of a specific region."""
        with self._lock:
            clamped = region.clamp(self.width, self.height)
            return self._current.crop(clamped.to_box())

    def compute_dirty_regions(self) -> list[Region]:
        """
        Compute dirty regions by comparing current buffer to flushed buffer.
        
        Returns a list of regions that have changed since the last flush.
        """
        with self._lock:
            dirty_regions = []
            
            # Compare pixel by pixel to find changed regions
            # For efficiency, we scan in 8x8 blocks (controller row alignment)
            block_size = 8
            
            for block_y in range(0, self.height, block_size):
                for block_x in range(0, self.width, block_size):
                    block_region = Region(
                        block_x,
                        block_y,
                        min(block_x + block_size, self.width),
                        min(block_y + block_size, self.height)
                    )
                    
                    if self._region_changed(block_region):
                        dirty_regions.append(block_region)
            
            return dirty_regions

    def _region_changed(self, region: Region) -> bool:
        """Check if a specific region has changed."""
        clamped = region.clamp(self.width, self.height)
        box = clamped.to_box()
        
        current_block = self._current.crop(box)
        flushed_block = self._flushed.crop(box)
        
        # Compare pixel data
        return list(current_block.getdata()) != list(flushed_block.getdata())

    def flush_region(self, region: Region) -> None:
        """
        Mark a region as flushed (copy from current to flushed buffer).
        
        This should be called after a successful hardware refresh.
        """
        with self._lock:
            clamped = region.clamp(self.width, self.height)
            box = clamped.to_box()
            
            # Copy the region from current to flushed
            region_image = self._current.crop(box)
            self._flushed.paste(region_image, (clamped.x1, clamped.y1))

    def flush_all(self) -> None:
        """Mark entire buffer as flushed."""
        with self._lock:
            self._flushed = self._current.copy()

    def clear(self) -> None:
        """Clear the entire buffer to white."""
        with self._lock:
            self._current = Image.new("1", (self.width, self.height), 255)
            self._flushed = Image.new("1", (self.width, self.height), 255)

