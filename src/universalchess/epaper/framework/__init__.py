"""ePaper framework core components.

This package must be importable in non-hardware environments. Importing the Manager
previously pulled in Waveshare drivers (via `manager.py`) which require Raspberry Pi
modules like `spidev`. Use lazy imports to avoid hardware initialization at import time.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "Widget": ("universalchess.epaper.framework.widget", "Widget"),
    "DITHER_PATTERNS": ("universalchess.epaper.framework.widget", "DITHER_PATTERNS"),
    "Manager": ("universalchess.epaper.framework.manager", "Manager"),
    "FrameBuffer": ("universalchess.epaper.framework.framebuffer", "FrameBuffer"),
    "Scheduler": ("universalchess.epaper.framework.scheduler", "Scheduler"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_IMPORTS.keys()))


__all__ = list(_LAZY_IMPORTS.keys())
