"""
Framebuffer management with dirty region tracking.
"""

from PIL import Image
from typing import List, Optional
from .regions import Region

try:
    from DGTCentaurMods.board.logging import log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class FrameBuffer:
    """Manages current and last-flushed framebuffers, computes dirty regions."""
    
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._current = Image.new("1", (width, height), 255)  # White
        self._flushed = Image.new("1", (width, height), 255)   # White
    
    def get_canvas(self) -> Image.Image:
        """Get the current framebuffer for rendering."""
        return self._current
    
    def compute_dirty_regions(self, block_size: int = 8) -> List[Region]:
        """Compute dirty regions by comparing current to flushed state."""
        dirty_regions = []
        
        for y in range(0, self.height, block_size):
            for x in range(0, self.width, block_size):
                x2 = min(x + block_size, self.width)
                y2 = min(y + block_size, self.height)
                
                current_block = self._current.crop((x, y, x2, y2))
                flushed_block = self._flushed.crop((x, y, x2, y2))
                
                current_bytes = current_block.tobytes()
                flushed_bytes = flushed_block.tobytes()
                
                if current_bytes != flushed_bytes:
                    # Debug: Log first few dirty regions with sample bytes
                    if len(dirty_regions) < 3:
                        current_sample = current_bytes[:16] if len(current_bytes) >= 16 else current_bytes
                        flushed_sample = flushed_bytes[:16] if len(flushed_bytes) >= 16 else flushed_bytes
                        log.debug(
                            f"FrameBuffer.compute_dirty_regions(): Dirty block at ({x},{y})-({x2},{y2}), "
                            f"current_bytes[:16]={current_sample.hex()}, flushed_bytes[:16]={flushed_sample.hex()}"
                        )
                    dirty_regions.append(Region(x, y, x2, y2))
        
        if dirty_regions:
            log.debug(f"FrameBuffer.compute_dirty_regions(): Found {len(dirty_regions)} dirty regions")
        
        return dirty_regions
    
    def flush_region(self, region: Region) -> None:
        """Mark a region as flushed by copying from current to flushed."""
        current_region = self._current.crop((region.x1, region.y1, region.x2, region.y2))
        self._flushed.paste(current_region, (region.x1, region.y1))
    
    def flush_all(self) -> None:
        """Mark entire framebuffer as flushed."""
        self._flushed = self._current.copy()
    
    def snapshot(self) -> Image.Image:
        """Get a snapshot of the current framebuffer."""
        return self._current.copy()
