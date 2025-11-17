"""
ePaper framework core components.
"""

from .widget import Widget
from .manager import Manager
from .regions import Region, merge_regions, expand_to_byte_alignment
from .framebuffer import FrameBuffer
from .scheduler import Scheduler

__all__ = ['Widget', 'Manager', 'Region', 'merge_regions', 'expand_to_byte_alignment', 
           'FrameBuffer', 'Scheduler']

