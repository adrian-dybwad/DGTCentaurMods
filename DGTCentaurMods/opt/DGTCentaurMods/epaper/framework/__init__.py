"""
ePaper framework core components.
"""

from .widget import Widget, DITHER_PATTERNS
from .manager import Manager
from .regions import Region, merge_regions, expand_to_byte_alignment
from .framebuffer import FrameBuffer
from .scheduler import Scheduler

__all__ = ['Widget', 'DITHER_PATTERNS', 'Manager', 'Region', 'merge_regions', 
           'expand_to_byte_alignment', 'FrameBuffer', 'Scheduler']

