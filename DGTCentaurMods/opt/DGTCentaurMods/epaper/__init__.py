"""Self-contained e-paper orchestration framework."""

from .controller import EPaperController
from .driver import EPaperDriver, NativeEPaperDriver, SimulatedEPaperDriver
from .framebuffer import FrameBuffer
from .regions import Region, RegionSet
from .scheduler import AdaptiveRefreshPlanner, RefreshMode, RefreshPlan
from .widgets.base import Widget

__all__ = [
    "EPaperController",
    "EPaperDriver",
    "SimulatedEPaperDriver",
    "NativeEPaperDriver",
    "FrameBuffer",
    "Region",
    "RegionSet",
    "AdaptiveRefreshPlanner",
    "RefreshPlan",
    "RefreshMode",
    "Widget",
]

