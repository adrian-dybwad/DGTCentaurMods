"""
Self-contained ePaper display framework with widget-based architecture.

Widgets only need to implement content rendering. The framework handles
all region tracking, merging, and refresh scheduling automatically.
"""

from .display_manager import DisplayManager

__all__ = ["DisplayManager"]

