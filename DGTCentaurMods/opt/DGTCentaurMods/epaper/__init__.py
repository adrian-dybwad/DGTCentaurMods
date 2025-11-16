"""High-level entry points for the DGTCentaurMods e-paper framework."""

from .manager import DisplayManager
from .strategy import RefreshPolicy
from .widgets import Widget

__all__ = [
    "DisplayManager",
    "RefreshPolicy",
    "Widget",
]

